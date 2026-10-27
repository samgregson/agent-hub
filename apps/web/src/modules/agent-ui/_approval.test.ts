import assert from "node:assert/strict";
import test from "node:test";

import {
  approvalLabel,
  approvalTarget,
  functionApprovalName,
  functionApprovalSummary,
  functionApprovalTechnicalDetails,
  isFunctionDefinitionApproval,
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

test("Function approvals expose a readable contract and retain technical details", () => {
  const proposal = {
    input_schema: {
      description: "Calculates the area of a rectangle.",
      examples: [{ length_m: 12, width_m: 5 }],
      properties: {
        length_m: {
          description: "Length in metres.",
          example: 12,
          type: "number",
        },
        width_m: {
          description: "Width in metres.",
          example: 5,
          type: "number",
        },
      },
      required: ["length_m", "width_m"],
      type: "object",
    },
    name: "Rectangle area",
    output_schema: {
      examples: [{ area_m2: 60 }],
      properties: {
        area_m2: {
          description: "Area in square metres.",
          example: 60,
          type: "number",
        },
      },
      required: ["area_m2"],
      type: "object",
    },
    source:
      'def transform(inputs, parameters): return {"area_m2": inputs["length_m"] * inputs["width_m"]}',
  };

  assert.equal(isFunctionDefinitionApproval("create_project_function"), true);
  assert.equal(isFunctionDefinitionApproval("update_project_function"), true);
  assert.equal(functionApprovalName(proposal), "Rectangle area");
  assert.deepEqual(functionApprovalSummary(proposal), {
    purpose: "Calculates the area of a rectangle.",
    inputs: [
      {
        name: "length_m",
        type: "number",
        description: "Length in metres.",
        required: true,
        example: 12,
      },
      {
        name: "width_m",
        type: "number",
        description: "Width in metres.",
        required: true,
        example: 5,
      },
    ],
    outputs: [
      {
        name: "area_m2",
        type: "number",
        description: "Area in square metres.",
        required: true,
        example: 60,
      },
    ],
    inputExample: "Object (length_m: 12; width_m: 5)",
    outputExample: "Object (area_m2: 60)",
  });
  assert.match(
    functionApprovalTechnicalDetails(proposal),
    /def transform\(inputs, parameters\)/,
  );
  assert.equal(
    approvalLabel("update_project_function"),
    "Approve Python Function revision",
  );
});
