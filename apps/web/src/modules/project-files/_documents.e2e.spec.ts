import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

// Real API, database, MarkItDown and PDF renderer; no mocked document responses.
test("upload documents, inspect original pages, read Markdown and retain warnings", async ({
  page,
  request,
}) => {
  test.skip(
    process.env.AGENT_HUB_DOCUMENT_E2E !== "1",
    "Requires the migrated API and real converter",
  );
  test.setTimeout(90000);
  const response = await request.post("/api/projects", {
    data: { name: "Document browser review" },
  });
  expect(response.status()).toBe(201);
  const project = await response.json();
  await page.goto("/");
  await page.locator("select").first().selectOption(project.id);
  await page
    .getByRole("button", { name: "Library", exact: true })
    .first()
    .click();
  const upload = page.getByLabel("Upload PDF or DOCX", { exact: true });
  await upload.setInputFiles("../../tests/fixtures/documents/bridge.pdf");
  const viewer = page.getByRole("region", { name: "Document viewer" });
  await expect(viewer.getByRole("heading", { name: "bridge.pdf" })).toBeVisible(
    { timeout: 30000 },
  );
  const image = viewer.getByRole("img", { name: "bridge.pdf, page 1" });
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
  await viewer.getByRole("button", { name: "Next page" }).click();
  await expect(viewer.getByLabel("PDF page")).toHaveValue("2");
  await viewer
    .getByRole("button", { name: "Extracted Markdown", exact: true })
    .click();
  await expect(viewer.locator("pre")).toContainText("span divided by 360");
  await viewer.getByRole("button", { name: "Previous page" }).click();
  await expect(viewer.locator("pre")).toContainText("12.5 metres");
  const originalUrl = await viewer
    .getByRole("link", { name: "Download original" })
    .getAttribute("href");
  const original = await request.get(originalUrl!);
  expect(await original.body()).toEqual(
    readFileSync("../../tests/fixtures/documents/bridge.pdf"),
  );
  await viewer
    .getByRole("button", { name: "Original page", exact: true })
    .click();
  await viewer.getByLabel("Document zoom").selectOption("150");
  await page.screenshot({
    path: "/tmp/agent-hub-document-viewer.png",
    fullPage: true,
  });
  await upload.setInputFiles("../../tests/fixtures/documents/scan.pdf");
  await expect(viewer.getByRole("heading", { name: "scan.pdf" })).toBeVisible({
    timeout: 30000,
  });
  await expect(viewer).toContainText("OCR or visual inspection");
  await upload.setInputFiles("../../tests/fixtures/documents/criteria.docx");
  await expect(
    viewer.getByRole("heading", { name: "criteria.docx" }),
  ).toBeVisible({ timeout: 30000 });
  await expect(viewer.locator("pre")).toContainText("imposed load 3 kPa");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(viewer).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "/tmp/agent-hub-document-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page.locator("select").first().selectOption(project.id);
  await page
    .getByRole("button", { name: "Library", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "bridge.pdf", exact: true }).click();
  await expect(
    viewer.getByRole("heading", { name: "bridge.pdf" }),
  ).toBeVisible();
});
