import assert from "node:assert/strict";
import test from "node:test";

import {
  approvalLabel,
  approvalTarget,
  isApprovalOnlyTool,
  proposedFileContent,
  resolvedApprovalReview,
  unifiedFileDiff,
} from "./_approval";

test("protected Project file tools use an approval card", () => {
  assert.equal(approvalLabel("write_file"), "Approve Project File change");
  assert.equal(isApprovalOnlyTool("write_file"), true);
  assert.equal(isApprovalOnlyTool("foundation_status"), false);
});

test("file review shows a new preview or an existing-file diff", () => {
  const args = { file_path: "/project/check.md", content: "# Revised\n" };
  assert.deepEqual(approvalTarget(args), {
    path: "/project/check.md",
    summary: "/project/check.md",
  });
  assert.equal(proposedFileContent("write_file", args, null), "# Revised\n");
  assert.match(
    unifiedFileDiff("/project/check.md", "# Original\n", "# Revised\n"),
    /-# Original\n\+# Revised/,
  );
  assert.equal(
    proposedFileContent(
      "edit_file",
      { old_string: "Original", new_string: "Revised" },
      "# Original\n",
    ),
    "# Revised\n",
  );
});

test("artifact and Dataset mutations receive specific labels", () => {
  assert.equal(
    approvalLabel("create_project_artifact"),
    "Approve Project Artifact creation",
  );
  assert.equal(
    approvalLabel("create_project_dataset"),
    "Approve Dataset change",
  );
  assert.deepEqual(approvalTarget({ artifact_id: "art-1" }), {
    artifactId: "art-1",
    summary: "Artifact art-1",
  });
  assert.equal(
    approvalLabel("delete_project_dataset"),
    "Approve Dataset deletion",
  );
  assert.deepEqual(approvalTarget({ dataset_id: "data-1" }), {
    summary: "Dataset data-1",
  });
  assert.deepEqual(
    approvalTarget(
      { definition_id: "def-1", record_id: "r-7" },
      "start_project_batch_run",
    ),
    { summary: "Definition def-1 · record r-7" },
  );
  assert.deepEqual(
    approvalTarget({ definition_id: "def-1" }, "start_project_batch_run"),
    { summary: "Definition def-1 · all records" },
  );
});

test("resolved approvals retain the proposed action for audit", () => {
  assert.equal(
    resolvedApprovalReview("write_file", { content: "# Proposal\n" }),
    "# Proposal\n",
  );
  assert.match(
    resolvedApprovalReview("edit_file", {
      old_string: "before",
      new_string: "after",
      replace_all: true,
    }),
    /Replace all matches\n--- Original text\nbefore\n\+\+\+ Proposed text\nafter/,
  );
});
