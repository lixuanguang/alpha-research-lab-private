"""Analysis test for invalid SQL-template configuration."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")


def _invalid_substitution_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, "SQL substitution keys must be non-empty @@TOKEN@@ values")
    return analysistest.end(env)


invalid_substitution_test = analysistest.make(
    _invalid_substitution_test_impl,
    expect_failure = True,
)
