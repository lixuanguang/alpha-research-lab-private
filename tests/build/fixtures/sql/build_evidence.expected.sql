SELECT artifact_target, artifact_digest
FROM build_artifact_digest
WHERE build_identity = 'hermetic-build-fixture'
ORDER BY artifact_target;
