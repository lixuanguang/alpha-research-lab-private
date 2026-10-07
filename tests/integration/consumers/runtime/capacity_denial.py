"""Show signed day-run grants deny use after expiry and after revocation, in one short session.

Run this from a frozen copy of this directory with the installed research interpreter,
as a cohort. One invocation builds and installs the four signed day-run owners, then:

- **expiry**: grants of the same signed form with a 10-minute life. One owner is
  claimed; before expiry a protective stop and a fresh claim both succeed; after
  expiry a new exposure and a new claim are refused, and a protective stop is applied;
- **revocation**: 26-hour grants. A second owner is claimed, its grant is revoked, and
  then a new exposure and a new claim are refused while a protective stop is applied.

Nothing renews either grant. Every request and receipt is retained under ``admin``.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import ClassVar, Literal
from uuid import uuid4

# third party library imports
from capacity_cohort import Cohort, Gate
from capacity_host import QuietHostPrecheck
from capacity_inputs import CapacityWorkload
from capacity_sustained import DayWorkload

# project library imports
from accounting import AccountLedger
from configuration import PaperAuthorization, PaperDeployment, PaperServiceConfiguration
from execution import (
    AccountControl,
    AccountDecision,
    AccountExecutionRequest,
    AccountObservation,
    AccountQuote,
    InstalledPaperAccount,
    OrderDecision,
    PaperOwner,
)
from strategies import OrderIntent

type Drill = Literal["expiry", "revocation"]


class _ExpiryWorkload(DayWorkload):
    """The day-run selection under grants of the same signed form with a 10-minute life."""

    grant_seconds: ClassVar[int] = 600


class DenialSession(Cohort):
    """Run both denial drills once, stopping at the first failed step."""

    workload_type: type[CapacityWorkload] = DayWorkload
    accounts: ClassVar[dict[Drill, str]] = {"expiry": "okx-shared", "revocation": "bitfinex-shared"}
    reasons: ClassVar[dict[Drill, str]] = {
        "expiry": "paper_authorization_expired_or_not_yet_valid",
        "revocation": "paper_authorization_revoked",
    }

    def _grant(self, drill: Drill) -> dict[str, object]:
        """Issue this drill's grants for every prepared account."""
        service = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        workload = (_ExpiryWorkload if drill == "expiry" else DayWorkload)(
            opening_at=service.accounts[0].configuration.opening_at,
            socket_root=Path(service.accounts[0].socket_path).parent,
        )
        return workload.finalize(
            self.root / "preparation", tuple(path.name for path in self.releases.values())
        )

    def _admin(self, drill: Drill, owner: PaperOwner | None = None) -> InstalledPaperAccount:
        """Address the drill's installed account, optionally as its current owner."""
        service = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        name = self.accounts[drill]
        definition = next(item for item in service.accounts if item.account_id == name)
        return InstalledPaperAccount(
            config=definition.configuration,
            launcher=self.launcher,
            target=self.root / f"target-{name}",
            policy=self.root / "release-policy.json",
            requests=self.output / drill / "admin",
            paper_owner=owner,
        )

    def _refused(self, admin: InstalledPaperAccount, request: AccountExecutionRequest) -> str:
        """Run a request that must fail and return the reason its receipt retained."""
        stem = hashlib.sha256(self.codec.encode_json(request)).hexdigest()
        prior = set(admin.requests.glob(f"{stem}.*.stderr"))
        try:
            admin.execute(request)
        except RuntimeError:
            receipts = set(admin.requests.glob(f"{stem}.*.stderr")) - prior
            if len(receipts) != 1:
                return "refused without a single retained receipt"
            for reason in (*self.reasons.values(), "paper_owner_stale_or_absent"):
                if reason.encode() in next(iter(receipts)).read_bytes():
                    return reason
            return "refused for another reason"
        return "admitted"

    def _exposure(self, drill: Drill, owner: PaperOwner) -> AccountExecutionRequest:
        """Build one new buy for the drill account's first selected instance."""
        service = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        name = self.accounts[drill]
        instance = next(item for item in service.instances if item.account_id == name)
        source = next(item for item in service.sources if item.name == instance.source)
        at = datetime.now(UTC)
        dimension = source.scenario.adverse.per
        price = source.scenario.adverse.model_copy(update={"value": Decimal(100)})
        return AccountExecutionRequest(
            action="admit",
            decision=AccountDecision(
                account_id=name,
                instance_id=instance.instance_id,
                decision=OrderDecision(
                    identity=f"denial-{drill}-exposure",
                    at=at,
                    intent=OrderIntent(
                        side="buy",
                        quantity=instance.quantity.model_copy(update={"dimension": dimension}),
                        limit=price,
                        time_in_force="ioc",
                    ),
                ),
                quote=AccountQuote(price=price, at=at),
                maximum_fee=instance.maximum_fee,
            ),
            paper_owner=owner,
        )

    def _reconcile(self, drill: Drill, admin: InstalledPaperAccount) -> None:
        """Refresh quotes and reconcile the stopped account's own facts, as recovery does.

        A claim after a stop requires a reconciliation later than the stop, so the
        refusal a drill observes is the grant's, not a stale account's.
        """
        service = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        name = self.accounts[drill]
        workload = DayWorkload(
            opening_at=service.accounts[0].configuration.opening_at,
            socket_root=Path(service.accounts[0].socket_path).parent,
        )
        venue = workload.venue_workload(name.split("-", maxsplit=1)[0])
        deployment = self.codec.decode_json(
            (self.root / f"preparation/deployment-{name}.json").read_bytes(), PaperDeployment
        )
        at = datetime.now(UTC)
        for scenario in deployment.scenarios:
            admin.observe(AccountQuote(price=venue.price("100", scenario.adverse.per), at=at))
        facts = admin.execute(AccountExecutionRequest(action="inspect"))
        snapshot = AccountLedger(facts.accounts[0].ledger).snapshot()
        opened = tuple(item.order for item in facts.net_orders if not item.order.is_terminal)
        if not admin.reconcile(
            AccountObservation(
                identity=f"denial-{drill}-{uuid4().hex}",
                at=datetime.now(UTC),
                snapshot=snapshot,
                open_orders=opened,
            )
        ):
            raise ValueError("denial account facts did not reconcile after the stop")

    def _claim(
        self, drill: Drill, admin: InstalledPaperAccount, label: str
    ) -> AccountExecutionRequest:
        """Build a replacement claim after the account's current stop and reconciliation."""
        self._reconcile(drill, admin)
        name = self.accounts[drill]
        stopped = admin.accounts()[0]
        return AccountExecutionRequest(
            action="claim_paper",
            account_id=name,
            owner_id=f"denial-{drill}-{label}",
            control=AccountControl(
                identity=f"denial-{drill}-{label}-restart",
                account_id=name,
                kind="restart",
                at=datetime.now(UTC),
                expected_control_identity=stopped.active_control_identity,
            ),
        )

    def _stop(self, drill: Drill, admin: InstalledPaperAccount, label: str) -> str:
        """Apply a protective stop and return its status."""
        name = self.accounts[drill]
        result = admin.control(
            AccountControl(
                identity=f"denial-{drill}-{label}-stop",
                account_id=name,
                kind="stop",
                at=datetime.now(UTC),
                reason="protective stop during a denial drill",
            )
        )
        return result.status

    def drill(self, drill: Drill) -> tuple[Gate, ...]:
        """Claim one owner under the drill's grant, end the grant, then try to use it."""
        authority = self._grant(drill)
        name = self.accounts[drill]
        service = self.codec.decode_json(
            (self.root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        definition = next(item for item in service.accounts if item.account_id == name)
        deployment = self.codec.decode_json(
            (self.root / f"preparation/deployment-{name}.json").read_bytes(), PaperDeployment
        )
        grant = self.codec.decode_json(
            (self.root / f"preparation/authorization-{name}.json").read_bytes(),
            PaperAuthorization,
        )
        admin = self._admin(drill)
        workload = DayWorkload(
            opening_at=definition.configuration.opening_at,
            socket_root=Path(definition.socket_path).parent,
        )
        owner = workload.install_and_claim(
            definition,
            deployment,
            grant,
            launcher=self.launcher,
            target=admin.target,
            policy=admin.policy,
            requests=admin.requests,
        )
        facts: dict[str, object] = {
            "account": name,
            "grant": grant.identity,
            "grant_life_seconds": (grant.expires_at - grant.valid_from).total_seconds(),
            "authority": authority,
        }
        gates: list[Gate] = []
        if drill == "expiry":
            # While current, a protective stop and a fresh claim both succeed.
            stopped = self._stop(drill, self._admin(drill, owner), "current")
            current = self._admin(drill).execute(self._claim(drill, self._admin(drill), "current"))
            owner = current.claimed_owner or owner
            gates.append(
                Gate(
                    "current_grant_admits_stop_and_claim",
                    stopped == "applied" and current.claimed_owner is not None,
                    {"stop": stopped, "claimed": current.claimed_owner is not None},
                )
            )
            wait = (grant.expires_at - datetime.now(UTC)).total_seconds() + 2
            facts["waited_seconds"] = max(0.0, wait)
            time.sleep(max(0.0, wait))
        else:
            revoked_at = datetime.now(UTC)
            self._admin(drill).execute(
                AccountExecutionRequest(
                    action="revoke_paper",
                    account_id=name,
                    authorization_id=grant.identity,
                    at=revoked_at,
                )
            )
            facts["revoked_at"] = revoked_at
        exposure = self._refused(self._admin(drill, owner), self._exposure(drill, owner))
        protective = self._stop(drill, self._admin(drill, owner), "ended")
        claim = self._refused(self._admin(drill), self._claim(drill, self._admin(drill), "ended"))
        renewed = self._admin(drill).execute(AccountExecutionRequest(action="inspect"))
        unchanged = all(
            activation.authorization == grant for activation in renewed.paper_activations
        )
        facts.update(exposure=exposure, protective=protective, claim=claim)
        (self.output / drill).mkdir(exist_ok=True)
        (self.output / drill / "facts.json").write_bytes(self.codec.encode_json(facts))
        gates.extend(
            (
                Gate(f"{drill}_denies_new_exposure", exposure == self.reasons[drill], exposure),
                Gate(f"{drill}_denies_new_claim", claim == self.reasons[drill], claim),
                Gate(f"{drill}_admits_protective_stop", protective == "applied", protective),
                Gate(f"{drill}_grant_not_renewed", unchanged, {"grant": grant.identity}),
            )
        )
        return tuple(gates)

    def run(self) -> None:
        """Build the day-run owners, then run the expiry and revocation drills."""
        self.output.mkdir(parents=True, exist_ok=False)
        awake = QuietHostPrecheck.hold_awake()
        try:
            self.step("freeze", self.freeze)
            self.step("candidate", self.candidate)
            self.step("expiry", partial(self.drill, "expiry"))
            self.step("revocation", partial(self.drill, "revocation"))
        finally:
            awake.terminate()
            awake.wait(5)


class _Arguments(argparse.Namespace):
    """Carry one session's absolute inputs."""

    output: Path
    repository: Path
    launcher: Path
    python: Path
    key_root: Path
    socket_base: Path
    label: str


def main() -> None:
    """Run one denial session into a fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "--output",
        "--repository",
        "--launcher",
        "--python",
        "--key-root",
        "--socket-base",
    ):
        parser.add_argument(option, type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args(namespace=_Arguments())
    session = DenialSession(
        args.output,
        repository=args.repository,
        launcher=args.launcher,
        python=args.python,
        key_root=args.key_root,
        socket_base=args.socket_base,
        label=args.label,
    )
    try:
        session.run()
    except Exception as error:
        print(f"denial session stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"denial session passed: {args.output}")


if __name__ == "__main__":
    main()
