// Fetch the static JSON produced by `kb export`.
//
// The Python side owns all parsing (markdown frontmatter, sections, edges),
// so the UI only has to fetch one file. If graph.json is missing, surface a
// helpful message — the empty-state component points the user at `kb export`.

export async function loadGraph(url = '/graph.json') {
  const resp = await fetch(url, { cache: 'no-cache' });
  if (!resp.ok) {
    throw new Error(
      `failed to fetch ${url}: ${resp.status} ${resp.statusText}`
    );
  }
  return resp.json();
}
