"""Hermetic SQL template expansion for repository-owned generated queries."""


def _sql_template_impl(ctx):
    for token in ctx.attr.substitutions:
        if not token.startswith("@@") or not token.endswith("@@") or len(token) <= 4:
            fail("SQL substitution keys must be non-empty @@TOKEN@@ values: %s" % token)

    output = ctx.actions.declare_file(ctx.label.name + ".sql")
    ctx.actions.expand_template(
        template = ctx.file.src,
        output = output,
        substitutions = ctx.attr.substitutions,
        is_executable = False,
    )
    return [DefaultInfo(files = depset([output]))]


sql_template = rule(
    implementation = _sql_template_impl,
    attrs = {
        "src": attr.label(allow_single_file = [".sql.tmpl"], mandatory = True),
        "substitutions": attr.string_dict(mandatory = True),
    },
)
