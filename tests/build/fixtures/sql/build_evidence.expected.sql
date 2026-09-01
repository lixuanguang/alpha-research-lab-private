SELECT artifact_target, artifact_digest
FROM build_artifact_digest
WHERE build_identity = 'b02-hermetic-fixture'
ORDER BY artifact_target;
