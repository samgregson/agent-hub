import assert from "node:assert/strict";
import test from "node:test";

import { approvalLabel, isApprovalOnlyTool } from "./_approval";

test("protected Project file tools use an approval card", () => {
  assert.equal(approvalLabel("write_file"), "Approve Project File change");
  assert.equal(isApprovalOnlyTool("write_file"), true);
  assert.equal(isApprovalOnlyTool("foundation_status"), false);
});
