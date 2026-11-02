import { IfcAPI } from "web-ifc";
import { BufferAttribute, BufferGeometry, Matrix4 } from "three";
export type IfcObject = {
  expressId: number;
  globalId: string;
  name: string;
  ifcType: string;
};
export type Part = {
  object: IfcObject;
  geometry: BufferGeometry;
  colour: string;
  opacity: number;
};
export type Model = {
  parts: Part[];
  api: IfcAPI;
  modelId: number;
  dispose: () => void;
};
export async function loadModel(text: string): Promise<Model> {
  const api = new IfcAPI();
  const parts: Part[] = [];
  let modelId: number | undefined;
  try {
    await api.Init(undefined, true);
    modelId = api.OpenModel(new TextEncoder().encode(text), {
      COORDINATE_TO_ORIGIN: true,
      MEMORY_LIMIT: 512 * 1024 * 1024,
      ALLOW_INCOMPATIBLE_SCHEMA_ALIASES: false,
    });
    if (modelId < 0 || !api.IsModelOpen(modelId))
      throw new Error("Could not open this IFC model.");
    const ids = new Set<string>();
    api.StreamAllMeshes(modelId, (mesh) => {
      const line = api.GetLine(modelId!, mesh.expressID);
      const globalId = line.GlobalId?.value;
      if (!globalId || ids.has(globalId))
        throw new Error("Missing or duplicate IFC GlobalId.");
      ids.add(globalId);
      const object: IfcObject = {
        expressId: mesh.expressID,
        globalId,
        name: line.Name?.value || "Unnamed object",
        ifcType: api.GetNameFromTypeCode(line.type),
      };
      for (let i = 0; i < mesh.geometries.size(); i++) {
        if (parts.length >= 20_000)
          throw new Error("Model exceeds the 20000 geometry-part limit.");
        const placed = mesh.geometries.get(i);
        const raw = api.GetGeometry(modelId!, placed.geometryExpressID);
        try {
          const data = api.GetVertexArray(
            raw.GetVertexData(),
            raw.GetVertexDataSize(),
          );
          const positions = new Float32Array(data.length / 2);
          const normals = new Float32Array(data.length / 2);
          for (let v = 0; v < data.length / 6; v++) {
            positions.set(data.subarray(v * 6, v * 6 + 3), v * 3);
            normals.set(data.subarray(v * 6 + 3, v * 6 + 6), v * 3);
          }
          const geometry = new BufferGeometry();
          geometry.setAttribute("position", new BufferAttribute(positions, 3));
          geometry.setAttribute("normal", new BufferAttribute(normals, 3));
          geometry.setIndex(
            new BufferAttribute(
              api
                .GetIndexArray(raw.GetIndexData(), raw.GetIndexDataSize())
                .slice(),
              1,
            ),
          );
          geometry.applyMatrix4(
            new Matrix4().fromArray(placed.flatTransformation),
          );
          const { x, y, z, w } = placed.color;
          parts.push({
            object,
            geometry,
            colour: `rgb(${Math.round(x * 255)},${Math.round(y * 255)},${Math.round(z * 255)})`,
            opacity: w,
          });
        } finally {
          raw.delete();
        }
      }
    });
    if (!parts.length)
      throw new Error("This IFC file contains no renderable geometry.");
    return {
      api,
      modelId,
      parts,
      dispose: () => {
        parts.forEach((part) => part.geometry.dispose());
        api.Dispose();
      },
    };
  } catch (error) {
    parts.forEach((part) => part.geometry.dispose());
    api.Dispose();
    throw error;
  }
}
