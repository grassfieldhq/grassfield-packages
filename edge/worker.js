// The edge of packages.grassfield.site (grassfield ADR-0033 h.2 and h.5, "pointer edge rule"; option (a)).
//
// scripts/serve.py is the reference: the fixed names of a channel (grassfield.db, grassfield.files, grassfield-notes.json,
// grassfield-catalog.v1.json, each with .sig) answer 302 to /<channel>/<arch>/snap/<id>/<name>, <id> read from
// /<channel>/<arch>/pointer ({"snapshot": "<id>"}) at each request, Cache-Control: no-store; a missing or malformed pointer
// gives 404. One pointer write switches a database and its signature together. Every other path is the bucket's object.
//
// Cache headers (h.5): never the fixed names, the pointer or a redirect; immutable names (snap/, packages and their
// signatures, catalog/*.png) one year, immutable; no 4xx or 5xx cached; anything else no-store.
// The Worker only reads the bucket (binding BUCKET); it holds no key.

const FIXED = /^\/(stable|beta)\/([a-z0-9_]+)\/((grassfield\.(db|files)|grassfield-(notes|catalog\.v1)\.json)(\.sig)?)$/;
const ID = /^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$/;
const IMMUTABLE_KEY = /^(stable|beta)\/[a-z0-9_]+\/(snap\/[^/]+\/[^/]+|catalog\/[0-9a-f]{64}\.png|[a-z0-9@_+][a-z0-9@._+-]*\.pkg\.tar\.(zst|xz|gz)(\.sig)?)$/;

export const NO_STORE = "no-store";
export const IMMUTABLE = "public, max-age=31536000, immutable";

function plain(status, text, headers = {}) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": NO_STORE, ...headers } });
}

async function pointerOf(env, channel, arch) {
  const object = await env.BUCKET.get(`${channel}/${arch}/pointer`);
  if (object === null) return null;
  try {
    const snap = JSON.parse(await object.text()).snapshot;
    return typeof snap === "string" && ID.test(snap) ? snap : null;
  } catch {
    return null;
  }
}

export function cacheControlFor(key) {
  return IMMUTABLE_KEY.test(key) ? IMMUTABLE : NO_STORE;
}

export async function handle(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return plain(405, "method not allowed", { Allow: "GET, HEAD" });
  }
  const url = new URL(request.url);
  const m = FIXED.exec(url.pathname);
  if (m) {
    const [, channel, arch, name] = m;
    const snap = await pointerOf(env, channel, arch);
    if (snap === null) return plain(404, "not found");
    return new Response(null, {
      status: 302,
      headers: { Location: `/${channel}/${arch}/snap/${snap}/${name}`, "Cache-Control": NO_STORE },
    });
  }

  let key;
  try {
    key = decodeURIComponent(url.pathname.slice(1));
  } catch {
    return plain(404, "not found");
  }
  if (key === "" || key.includes("\0") || key.split("/").some((s) => s === "" || s === "." || s === "..")) {
    return plain(404, "not found");
  }
  const headers = new Headers();
  const options = { onlyIf: request.headers, range: request.headers };
  const object = request.method === "HEAD" ? await env.BUCKET.head(key) : await env.BUCKET.get(key, options);
  if (object === null) return plain(404, "not found");
  object.writeHttpMetadata(headers);
  headers.set("ETag", object.httpEtag);
  // pacman gives a downloaded file the server's Last-Modified as its mtime (curl -R) and asks with If-Modified-Since: with
  // none, the file's mtime is the download time, and a database fetched before a newer snapshot's pointer write, or by a
  // client whose clock runs ahead, would be answered 304 for the new one. serve.py sends it too (http.server).
  if (object.uploaded instanceof Date) headers.set("Last-Modified", object.uploaded.toUTCString());
  headers.set("Accept-Ranges", "bytes");
  headers.set("Cache-Control", cacheControlFor(key));
  if (request.method === "HEAD") {
    headers.set("Content-Length", String(object.size));
    return new Response(null, { status: 200, headers });
  }
  if (!("body" in object) || object.body === undefined) {
    // A failed precondition: R2 returns the metadata without a body.
    const notModified = request.headers.has("If-None-Match") || request.headers.has("If-Modified-Since");
    headers.set("Cache-Control", NO_STORE);
    return new Response(null, { status: notModified ? 304 : 412, headers });
  }
  let status = 200;
  if (request.headers.has("Range") && object.range) {
    const r = object.range;
    let start, end;
    if (r.suffix !== undefined) {
      start = Math.max(0, object.size - r.suffix);
      end = object.size - 1;
    } else {
      start = r.offset ?? 0;
      end = r.length !== undefined ? start + r.length - 1 : object.size - 1;
    }
    headers.set("Content-Range", `bytes ${start}-${end}/${object.size}`);
    headers.set("Content-Length", String(end - start + 1));
    status = 206;
  } else {
    headers.set("Content-Length", String(object.size));
  }
  return new Response(object.body, { status, headers });
}

export default {
  fetch(request, env) {
    return handle(request, env);
  },
};
