import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { chromium } from "@playwright/test";

const html = await readFile(
  new URL("../dist/index.html", import.meta.url),
  "utf8",
);
const ifcText = await readFile(new URL("./beam.ifc", import.meta.url), "utf8");
const globalId = ifcText.match(/IFCBEAM\('([^']+)'/)[1];
const view = {
  kind: "ifc.view",
  schemaVersion: "1",
  ifcText,
  modelSha256: "fixture",
  metadata: [{ globalId, values: { status: "pass", utilisation: 0.75 } }],
  colourBy: "status",
};
const csp =
  "default-src 'none'; base-uri 'none'; connect-src 'none'; font-src data:; form-action 'none'; frame-ancestors 'self'; frame-src 'none'; img-src data:; script-src 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'unsafe-inline'";
let current = view;
const server = createServer((request, response) => {
  if (request.url === "/app") {
    response.writeHead(200, {
      "Content-Type": "text/html",
      "Content-Security-Policy": csp,
    });
    response.end(html);
  } else {
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(`<!doctype html><iframe id="app" sandbox="allow-scripts" src="/app" style="width:100%;height:1000px;border:0"></iframe><script>
      const frame=document.getElementById('app');
      addEventListener('message',event=>{
        if(event.source!==frame.contentWindow)return;
        const m=event.data;
        if(m.method==='ui/initialize')frame.contentWindow.postMessage({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2026-01-26',hostInfo:{name:'Test host',version:'1'},hostCapabilities:{},hostContext:{}}},'*');
        if(m.method==='ui/notifications/initialized')frame.contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{content:[],structuredContent:${JSON.stringify(current).replaceAll("<", "\\u003c")}}},'*');
      });
    </script>`);
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || chromium.executablePath(),
  args: [
    "--no-sandbox",
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});
const page = await browser.newPage({ viewport: { width: 1200, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (msg) => {
  if (msg.type() === "error") console.error(msg.text().slice(0, 1000));
});
try {
  const url = `http://127.0.0.1:${server.address().port}`;
  await page.goto(url);
  const app = page.frameLocator("#app");
  await app
    .getByLabel("Object", { exact: true })
    .selectOption(globalId, { timeout: 30000 });
  await app.getByRole("heading", { name: "Beam B-01" }).waitFor();
  await app
    .getByText("IFC attributes and property sets", { exact: true })
    .click();
  await app.getByText('"B-01"', { exact: false }).waitFor();
  assert.equal(await app.locator("canvas").count(), 1);
  await app.getByLabel("Metadata name", { exact: true }).fill("review");
  await app.getByLabel("Value", { exact: true }).fill("approved");
  await app.getByRole("button", { name: "Assign to selected object" }).click();
  await app.getByLabel("Colour by", { exact: true }).selectOption("review");
  await app.getByRole("button", { name: "Export view inputs" }).click();
  const exported = JSON.parse(
    await app
      .getByRole("textbox", { name: "Portable prepare_ifc_view inputs" })
      .inputValue(),
  );
  assert.equal(exported.metadata[0].values.review, "approved");
  assert.equal(exported.metadata[0].globalId, globalId);
  assert.equal(exported.colour_by, "review");
  assert.equal(exported.ifc_text, ifcText);
  await page.screenshot({ path: "/tmp/ifc-viewer-desktop.png" });
  await page.setViewportSize({ width: 390, height: 1000 });
  assert.equal(
    await app
      .locator("body")
      .evaluate((element) => element.scrollWidth <= element.clientWidth),
    true,
  );
  await page.screenshot({ path: "/tmp/ifc-viewer-mobile.png" });
  // Reopen the same captured result through the Artifact envelope.
  current = { artifact: { title: "Saved IFC" }, payload: { output: view } };
  await page.reload();
  await app
    .getByLabel("Object", { exact: true })
    .selectOption(globalId, { timeout: 30000 });
  await app.getByRole("heading", { name: "Beam B-01" }).waitFor();
  await app
    .getByLabel("Open IFC file locally")
    .setInputFiles(new URL("./beam.ifc", import.meta.url).pathname);
  await app.getByLabel("Object", { exact: true }).selectOption(globalId);
  await app.getByRole("heading", { name: "Beam B-01" }).waitFor();
  assert.equal(
    await app
      .getByLabel("Colour by", { exact: true })
      .locator("option")
      .count(),
    1,
  );
  assert.deepEqual(errors, []);
  console.log(
    "IFC browser smoke passed: sandboxed WASM, geometry, properties, metadata, colours, export, mobile and saved Artifact.",
  );
} catch (error) {
  console.error("App errors:", errors);
  for (const frame of page.frames())
    console.error(
      await frame
        .locator("body")
        .innerText()
        .catch(() => "Unavailable frame")
        .then((text) => text.slice(0, 3000)),
    );
  await page.screenshot({ path: "/tmp/ifc-viewer-failure.png" });
  throw error;
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
