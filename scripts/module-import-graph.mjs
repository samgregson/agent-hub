/** Return one directed dependency cycle, or null when the Module graph is acyclic. */
export function findDependencyCycle(dependencies) {
  const visited = new Set();
  const active = new Set();
  const path = [];

  function visit(moduleName) {
    if (active.has(moduleName)) {
      return [...path.slice(path.indexOf(moduleName)), moduleName];
    }
    if (visited.has(moduleName)) return null;
    visited.add(moduleName);
    active.add(moduleName);
    path.push(moduleName);
    for (const dependency of dependencies.get(moduleName) ?? []) {
      const cycle = visit(dependency);
      if (cycle) return cycle;
    }
    path.pop();
    active.delete(moduleName);
    return null;
  }

  for (const moduleName of dependencies.keys()) {
    const cycle = visit(moduleName);
    if (cycle) return cycle;
  }
  return null;
}
