# Alpha Research Platform

A research and paper-trading platform for OKX and Bitfinex spot. It covers market-data
capture and publication, research studies and costed backtests, a versioned feature
store, candidate packaging, and supervised paper and shadow trading with independent
risk, reconciliation, monitoring and recovery.

Once the infrastructure passes [QR onboarding acceptance](roadmap/qr-onboarding.md),
quant research starts with an economic question: can an observable market state improve
a trading decision after costs, delay and risk? The
[research milestones](research/program.md#post-infrastructure-research-milestones) are
planned, not started.

Live trading is out of scope. It is
[reconsidered](roadmap/overview.md#live-trading-kept-in-view) only after profitable
out-of-sample and forward paper evidence, net of transaction costs, slippage and
applicable gas fees. Paper economics do not qualify venue execution.

## Start here

| If you are | Read |
| --- | --- |
| A quant researcher | [Quickstart](research/quickstart.md), then the [research guide](research/guide.md) |
| Developing the platform | [Development environment](development/environment.md), [engineering standards](development/engineering-standards.md), [development workflow](governance/workflow.md) |
| Operating paper services | [Operations runbook](governance/operations.md) and [local services](local-services/lakefs.md) |
| Tracking delivery | [Roadmap](roadmap/overview.md) |

## System map

Paths are under `src/`. Solid arrows are imports or calls; dotted arrows are handoffs
through retained artifacts.

```mermaid
flowchart TD
    researcher(("Researcher"))
    operator(("Operator"))

    subgraph market["Market data"]
        capture["Market capture<br/>market_data/collection/runner.py"]
        publication["Dataset publication<br/>market_data/datasets/publication.py"]
        query["Market-data queries<br/>market_data/query/reader.py"]
    end

    subgraph research["Research"]
        observations["Observations<br/>research/observations/windows.py"]
        features[("Feature store<br/>research/features/store.py")]
        studies["Research studies<br/>research/studies/"]
        simulation["Spot simulation<br/>simulation/"]
        backtests["Costed backtests<br/>applications/backtest/workflow.py"]
    end

    subgraph runtime["Candidate runtime"]
        packaging["Candidate packaging<br/>runtime/packaging.py"]
        components["Runtime components<br/>runtime/components.py"]
        worker["Candidate worker<br/>runtime/candidate_worker.py"]
        decisions["Shared decision runtime<br/>runtime/portfolio.py"]
    end

    subgraph paper["Paper operations"]
        supervisor["Paper services<br/>applications/execute/services.py"]
        accounts["Account journal<br/>execution/accounts.py"]
        accountstate[("Account state<br/>execution/account_state.py")]
        admission["Account admission<br/>execution/account_admission.py"]
        risk["Risk budgets and spot limits<br/>risk/budgets.py, risk/spot.py"]
        allocation["Portfolio allocation<br/>portfolio/"]
        recovery["Account backup and restore<br/>runtime/account_recovery.py"]
        monitor["Service monitoring<br/>applications/execute/service_monitor.py"]
    end

    subgraph telemetry["Telemetry"]
        events["Monitoring events<br/>telemetry/events.py"]
        tstore[("Telemetry store<br/>telemetry/store.py")]
        metrics["Metrics<br/>telemetry/metrics.py"]
        tconfig["Monitoring configuration<br/>telemetry/configuration.py"]
        tdefaults["Monitoring defaults<br/>telemetry/defaults.py"]
        dashboard["Dashboards and alerts<br/>telemetry/dashboard.py"]
    end

    subgraph venue["Test-venue path (OKX demo)"]
        venueapp["Venue operations<br/>applications/execute/venue.py"]
        gateway["Venue gateway<br/>execution/venue_gateway.py"]
    end

    subgraph foundations["Shared foundations"]
        configuration["Configuration<br/>configuration/"]
        strategies["Strategy decisions<br/>strategies/decisions.py"]
        units["Financial units<br/>financial_units/models.py"]
        accounting["Accounting ledger<br/>accounting/"]
    end

    researcher -->|"captures"| capture
    capture -.->|"recordings"| publication
    publication -.->|"published datasets"| query
    query -->|"as-of reads"| observations
    observations -->|"materializes"| features
    features -->|"study inputs"| studies
    researcher -->|"frames questions"| studies
    studies --> simulation
    backtests --> studies
    backtests --> simulation
    backtests --> query
    studies -.->|"selected candidate"| packaging
    packaging -.->|"signed candidate"| worker
    worker --> components
    components --> strategies

    operator -->|"operates"| supervisor
    supervisor -->|"source captures"| capture
    supervisor -->|"served features"| features
    supervisor -->|"runs candidates"| worker
    supervisor --> decisions
    supervisor -->|"account requests over sockets"| accounts
    accounts --> accountstate
    accounts --> admission
    admission --> risk
    accounts --> allocation
    accountstate --> accounting
    operator -->|"backup and restore"| recovery
    recovery -.->|"stopped workspaces"| accounts
    supervisor -->|"monitors"| monitor
    monitor -->|"retains events"| tstore

    events --> tstore
    events --> metrics
    tstore -->|"panel inputs"| dashboard
    metrics -->|"evaluates panels"| dashboard
    tdefaults --> tconfig
    tconfig -->|"configures views"| dashboard

    operator -->|"demo orders"| venueapp
    venueapp --> gateway

    configuration -.->|"signed service and account definitions"| supervisor
    units -.-> accounting
```

## Documentation map

| Area | Pages |
| --- | --- |
| Research | [Quickstart](research/quickstart.md), [research guide](research/guide.md), [API notes](research/api.md), [study protocol](research/study-protocol.md), [ranked agenda](research/agenda.md), [notebooks](research/notebooks.md), [research program](research/program.md), [saved L2 backtest](research/l2-book-backtest.md) |
| Architecture | [Overview](architecture/overview.md), [platform design](architecture/platform-design.md), [research and simulation](architecture/research-and-simulation-design.md), [portfolio and execution](architecture/portfolio-and-execution-design.md), [runtime and operations](architecture/runtime-and-operations-design.md), [economic and market data](architecture/economic-and-market-data-design.md), [instrument identity](architecture/instrument-identity.md), [venue calendars](architecture/venue-calendar.md), [financial units](architecture/financial-units.md), [dependency admission](architecture/dependency-admission.md) |
| Packages | [Market data](packages/market-data.md), [accounting](packages/accounting.md), [execution](packages/execution.md), [portfolio](packages/portfolio.md), [risk](packages/risk.md), [runtime](packages/runtime.md), [simulation](packages/simulation.md), [strategies](packages/strategies.md), [telemetry](packages/telemetry.md) |
| Research packages | [Experiments](packages/research-experiments.md), [features](packages/research-features.md), [labels](packages/research-labels.md), [models](packages/research-models.md), [observations](packages/research-observations.md), [studies](packages/research-studies.md) |
| Applications | [Execute](packages/execute-application.md), [paper](packages/paper-application.md) |
| Data | [Data contracts](data/contracts.md), [point-in-time semantics](data/point-in-time-semantics.md), [OKX market data](data/okx-market-data.md), [L3 collectors](data/l3-collectors.md), [data sources](data-sources/overview.md) |
| Development | [Environment](development/environment.md), [testing](development/testing.md), [engineering standards](development/engineering-standards.md), [typing stubs](development/typing-stubs.md) |
| Local services | [lakeFS](local-services/lakefs.md), [ClearML](local-services/clearml.md), [Feast worker](local-services/feast-worker.md) |
| Governance | [Development workflow](governance/workflow.md), [operations runbook](governance/operations.md), [dependency locks](governance/dependency-locks.md) |
| Roadmap | [Overview](roadmap/overview.md), [QR onboarding acceptance](roadmap/qr-onboarding.md), [runtime capacity](roadmap/runtime-capacity.md), [research capacity](roadmap/research-capacity.md) |
