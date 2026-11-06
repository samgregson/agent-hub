import { App as McpApp } from "@modelcontextprotocol/ext-apps";
import { Canvas } from "@react-three/fiber";
import { Bounds, OrbitControls } from "@react-three/drei";
import { Component, useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { DoubleSide } from "three";
import {
  assignMetadata,
  colourMap,
  readView,
  scaleLegend,
  valueKey,
  type View,
} from "./metadata";
import { loadModel, type IfcObject, type Model } from "./model";

class RenderBoundary extends Component<
  { children: ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <p role="alert">
        3D rendering is unavailable. Check that your browser supports WebGL.
      </p>
    ) : (
      this.props.children
    );
  }
}
function Viewer({ initial }: { initial: View }) {
  const [view, setView] = useState(initial);
  const [model, setModel] = useState<Model | null>(null);
  const [error, setError] = useState("");
  const [selected, select] = useState<IfcObject | null>(null);
  const [properties, setProperties] = useState<unknown>(null);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [exporting, setExporting] = useState(false);
  const [fit, setFit] = useState(0);
  useEffect(() => {
    let active = true;
    let loaded: Model | undefined;
    loadModel(view.ifcText)
      .then((result) => {
        if (!active) {
          result.dispose();
          return;
        }
        loaded = result;
        setModel(result);
      })
      .catch((reason) => {
        if (active) setError(String(reason));
      });
    return () => {
      active = false;
      loaded?.dispose();
    };
  }, [view.ifcText]);
  useEffect(() => {
    let active = true;
    setProperties(null);
    if (model && selected)
      Promise.all([
        model.api.properties.getItemProperties(
          model.modelId,
          selected.expressId,
          false,
        ),
        model.api.properties.getPropertySets(
          model.modelId,
          selected.expressId,
          true,
          false,
        ),
        model.api.properties.getPropertySets(
          model.modelId,
          selected.expressId,
          true,
          true,
        ),
      ])
        .then(([attributes, propertySets, typePropertySets]) => {
          if (active)
            setProperties({ attributes, propertySets, typePropertySets });
        })
        .catch((reason) => {
          if (active) setProperties({ error: String(reason) });
        });
    return () => {
      active = false;
    };
  }, [model, selected]);
  const rows = view.metadata;
  const keys = [
    ...new Set(rows.flatMap((row) => Object.keys(row.values))),
  ].sort();
  const colours = useMemo(
    () => colourMap(rows, view.colourBy ?? "", view.colourScale),
    [rows, view.colourBy, view.colourScale],
  );
  const byId = useMemo(
    () => new Map(rows.map((row) => [row.globalId, row.values])),
    [rows],
  );
  const objects = useMemo(
    () => [
      ...new Map(
        model?.parts.map((part) => [part.object.globalId, part.object]) ?? [],
      ).values(),
    ],
    [model],
  );
  const objectIds = new Set(objects.map((object) => object.globalId));
  const unmatched = rows.filter((row) => model && !objectIds.has(row.globalId));
  function assign() {
    if (!selected) return;
    try {
      let scalar: unknown;
      try {
        scalar = JSON.parse(value);
      } catch {
        scalar = value;
      }
      if (
        scalar !== null &&
        !["string", "number", "boolean"].includes(typeof scalar)
      )
        throw new Error("Enter text, a number, true, false or null.");
      setView({
        ...view,
        metadata: assignMetadata(
          rows,
          selected.globalId,
          key.trim(),
          scalar as string | number | boolean | null,
        ),
      });
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  }
  return (
    <main>
      <header className="view-heading">
        <h1>Model</h1>
        <p>IFC objects and assigned metadata</p>
      </header>
      <div className="toolbar">
        <label>
          Colour by{" "}
          <select
            aria-label="Colour by"
            value={view.colourBy ?? ""}
            onChange={(event) =>
              setView({ ...view, colourBy: event.target.value || null })
            }
          >
            <option value="">IFC materials</option>
            {keys.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <button onClick={() => setFit((n) => n + 1)}>Fit model</button>
        <button onClick={() => setExporting(!exporting)}>
          Export view inputs
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {unmatched.length > 0 && (
        <p role="alert">
          {unmatched.length} metadata rows have no rendered object in this
          model.
        </p>
      )}
      {!model && !error && <p role="status">Loading IFC geometry…</p>}
      <div className="workspace">
        <section className="scene" aria-label="IFC 3D model">
          {model && (
            <RenderBoundary>
              <Canvas
                camera={{ position: [10, 10, 10], near: 0.01, far: 100000 }}
                onPointerMissed={() => select(null)}
              >
                <color attach="background" args={["#eef2f6"]} />
                <ambientLight intensity={1.6} />
                <directionalLight position={[10, 20, 10]} intensity={2} />
                <Bounds key={fit} fit clip observe margin={1.25}>
                  <group dispose={null}>
                    {model.parts.map((part, index) => {
                      const entry = byId.get(part.object.globalId);
                      const colour = view.colourBy
                        ? (colours.get(valueKey(entry?.[view.colourBy])) ??
                          "#94a3b8")
                        : part.colour;
                      return (
                        <mesh
                          key={index}
                          geometry={part.geometry}
                          onClick={(event) => {
                            event.stopPropagation();
                            select(part.object);
                          }}
                        >
                          <meshStandardMaterial
                            color={colour}
                            side={DoubleSide}
                            emissive={
                              selected?.globalId === part.object.globalId
                                ? "#4b3800"
                                : "#000000"
                            }
                            transparent={part.opacity < 1}
                            opacity={part.opacity}
                          />
                        </mesh>
                      );
                    })}
                  </group>
                </Bounds>
                <OrbitControls makeDefault />
              </Canvas>
            </RenderBoundary>
          )}
        </section>
        <aside aria-label="Object metadata">
          <label>
            Object{" "}
            <select
              aria-label="Object"
              value={selected?.globalId ?? ""}
              onChange={(event) =>
                select(
                  objects.find(
                    (object) => object.globalId === event.target.value,
                  ) ?? null,
                )
              }
            >
              <option value="">Select an object</option>
              {objects.map((object) => (
                <option key={object.globalId} value={object.globalId}>
                  {object.name} · {object.globalId}
                </option>
              ))}
            </select>
          </label>
          {selected ? (
            <>
              <h2>{selected.name}</h2>
              <p>{selected.ifcType}</p>
              <p className="id">
                GlobalId: {selected.globalId}
                <br />
                Express ID: {selected.expressId}
              </p>
              <h3>Assigned metadata</h3>
              <pre>
                {JSON.stringify(byId.get(selected.globalId) ?? {}, null, 2)}
              </pre>
              <label>
                Metadata name
                <input
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                  maxLength={128}
                />
              </label>
              <label>
                Value
                <input
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                />
              </label>
              <button onClick={assign}>Assign to selected object</button>
              <details>
                <summary>IFC attributes and property sets</summary>
                <pre>
                  {properties
                    ? JSON.stringify(properties, null, 2)
                    : "Loading properties…"}
                </pre>
              </details>
            </>
          ) : (
            <p>Click geometry or choose an object to inspect its properties.</p>
          )}
        </aside>
      </div>
      {view.colourBy && (
        <section aria-label="Colour legend" className="legend">
          {[
            ...(view.colourScale?.key === view.colourBy
              ? scaleLegend(view.colourScale)
              : colours),
          ].map(([label, colour]) => (
            <span key={label}>
              <i style={{ background: colour }} />
              {label}
            </span>
          ))}
        </section>
      )}
      <p className="notice">
        Metadata edits are local to this preview. Export these inputs and call
        prepare_ifc_view to save a new result. The IFC source is unchanged.
        Numeric values use{" "}
        {view.colourScale?.key === view.colourBy
          ? "the supplied colour scale"
          : "discrete colours"}
        .
      </p>
      {exporting && (
        <label>
          Portable prepare_ifc_view inputs
          <textarea
            aria-label="Portable prepare_ifc_view inputs"
            readOnly
            rows={12}
            value={JSON.stringify(
              {
                ifc_text: view.ifcText,
                metadata: rows,
                colour_by: view.colourBy,
                colour_scale: view.colourScale ?? null,
              },
              null,
              2,
            )}
            onFocus={(event) => event.currentTarget.select()}
          />
        </label>
      )}
    </main>
  );
}
function App() {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const app = new McpApp({ name: "IFC viewer", version: "0.1.0" }, {});
    app.ontoolresult = (result) => {
      try {
        setView(readView(result.structuredContent));
        setError("");
      } catch (reason) {
        setError(String(reason));
      }
    };
    const applyTheme = (theme: string | undefined) => {
      document.documentElement.dataset.theme =
        theme === "dark" ? "dark" : "light";
    };
    app.onhostcontextchanged = () => applyTheme(app.getHostContext()?.theme);
    const exitExpanded = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        app.getHostContext()?.displayMode === "fullscreen"
      ) {
        event.preventDefault();
        void app.requestDisplayMode({ mode: "inline" }).catch(() => {});
      }
    };
    window.addEventListener("keydown", exitExpanded);
    app
      .connect()
      .then(() => applyTheme(app.getHostContext()?.theme))
      .catch((reason) => setError(String(reason)));
    return () => {
      window.removeEventListener("keydown", exitExpanded);
      void app.close();
    };
  }, []);
  async function openFile(file: File | undefined) {
    if (!file) return;
    try {
      if (file.size > 25_000_000)
        throw new Error("Local IFC files are limited to 25 MB.");
      const text = await file.text();
      if (!text.trimStart().startsWith("ISO-10303-21;"))
        throw new Error("Choose an IFC STEP file.");
      setView({
        kind: "ifc.view",
        schemaVersion: "1",
        ifcText: text,
        metadata: [],
        colourBy: null,
        modelSha256: "local-unsaved",
      });
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  }
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {view ? (
        <Viewer key={JSON.stringify(view)} initial={view} />
      ) : (
        <p role="status">
          Waiting for an IFC result, or choose a local IFC file.
        </p>
      )}
      <details className="local-file">
        <summary>Open another IFC file locally</summary>
        <label className="file-input">
          Open IFC file locally
          <input
            type="file"
            accept=".ifc"
            onChange={(event) => {
              void openFile(event.target.files?.[0]);
            }}
          />
        </label>
      </details>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
