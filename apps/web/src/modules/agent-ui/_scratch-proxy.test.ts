import assert from "node:assert/strict";
import test from "node:test";

import { backendRequestUrl } from "../../shared/http/_request-url";

test("forwards a Thread-local scratch path to the API", async () => {
  assert.equal(
    backendRequestUrl(
      "http://localhost:8000",
      "/api/projects/project-1/threads/thread-1/scratch",
      "http://web.test/api/projects/project-1/threads/thread-1/scratch?path=%2Fscratch%2Fnotes.md",
    ),
    "http://localhost:8000/api/projects/project-1/threads/thread-1/scratch?path=%2Fscratch%2Fnotes.md",
  );
});

test("does not append a Project file path query twice", async () => {
  assert.equal(
    backendRequestUrl(
      "http://localhost:8000",
      "/api/projects/project-1/files?path=%2Fproject%2Ftesting.txt",
      "http://web.test/api/projects/project-1/files?path=%2Fproject%2Ftesting.txt",
    ),
    "http://localhost:8000/api/projects/project-1/files?path=%2Fproject%2Ftesting.txt",
  );
});
