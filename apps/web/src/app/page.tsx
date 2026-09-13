const views = ["Chats", "Artifacts", "Sources", "Plugins"];

export default function Home() {
  return (
    <main className="shell">
      <header className="titlebar">
        <span className="mark">A</span>
        <span className="project">No project selected</span>
        <span className="foundation">Foundation shell</span>
      </header>
      <nav aria-label="Project views" className="rail">
        {views.map((view) => (
          <button
            aria-label={view}
            className="railButton"
            key={view}
            type="button"
          >
            {view.slice(0, 1)}
          </button>
        ))}
      </nav>
      <aside className="navigator">
        <strong>Chats</strong>
        <p>Project navigation arrives in Slice 1.</p>
      </aside>
      <section className="chat">
        <div>
          <p className="eyebrow">Agent Hub</p>
          <h1>The foundation is running.</h1>
          <p>Agent streaming arrives in Slice 2.</p>
        </div>
      </section>
      <aside className="artifact">
        <strong>Artifact workspace</strong>
        <p>MCP App hosting arrives in Slice 7.</p>
      </aside>
    </main>
  );
}
