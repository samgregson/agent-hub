import assert from "node:assert/strict";
import test from "node:test";

import { approvalLabel, isApprovalOnlyTool } from "./_approval";

test("Artifact tools have specific approval labels and do not render raw tool cards", () => {
  assert.equal(
    approvalLabel("create_foundation_status_artifact"),
    "Approve Project Artifact creation",
  );
  assert.equal(
    approvalLabel("set_foundation_status_artifact_status"),
    "Approve Project Artifact change",
  );
  assert.equal(isApprovalOnlyTool("create_foundation_status_artifact"), true);
  assert.equal(
    isApprovalOnlyTool("set_foundation_status_artifact_status"),
    true,
  );
});
