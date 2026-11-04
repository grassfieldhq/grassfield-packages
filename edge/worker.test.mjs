// Unit test of the Worker against scripts/serve.py (the reference of the edge rule), plain node, a mocked bucket over a tree.
//   node --test edge/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, utimesSync, readFileSync, statSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { handle, cacheControlFor, IMMUTABLE, NO_STORE } from "./worker.js";

const here = dirname(fileURLToPath(import.meta.url));
const SNAP = "20261104T120000Z-0123456789ab";
const OTHER = "20261104T130000Z-ba9876543210";
const NAMES = ["grassfield.db", "grassfield.db.sig", "grassfield.files", "grassfield.files.sig", "grassfield-notes.json",
  "grassfield-notes.json.sig", "grassfield-catalog.v1.json", "grassfield-catalog.v1.json.sig"];

const root = mkdtempSync(join(tmpdir(), "edge-"));
function put(rel, data) {
  mkdirSync(dirname(join(root, rel)), { recursive: true });
  writeFileSync(join(root, rel), data);
}
put("stable/x86_64/pointer", JSON.stringify({ snapshot: SNAP }) + "\n");
put("beta/x86_64/pointer", "{not json");
put("stable/arm64/pointer", JSON.stringify({ snapshot: "../../etc" }));
for (const n of NAMES) put(`stable/x86_64/snap/${SNAP}/${n}`, `content of ${n}`);
put("stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst", "0123456789");

// A mocked R2 binding over the tree: get(key, {range, onlyIf}), head(key).
function object(key, body, mtimeMs) {
  const size = body.length;
  return {
    size,
    key,
    uploaded: new Date(mtimeMs),
    httpEtag: `"etag-${key.length}"`,
    writeHttpMetadata(h) { h.set("Content-Type", "application/octet-stream"); },
    text: async () => body.toString("utf8"),
    body: new Blob([body]).stream(),
  };
}
const BUCKET = {
  async get(key, options = {}) {
    const p = join(root, key);
    if (!existsSync(p) || !statSync(p).isFile()) return null;
    const data = readFileSync(p);
    const o = object(key, data, statSync(p).mtimeMs);
    const range = options.range?.get?.("range");
    if (range) {
      const m = /^bytes=(\d+)-(\d*)$/.exec(range);
      const offset = Number(m[1]);
      const end = m[2] === "" ? data.length - 1 : Number(m[2]);
      o.range = { offset, length: end - offset + 1 };
      o.body = new Blob([data.subarray(offset, end + 1)]).stream();
    }
    if (options.onlyIf?.get?.("if-none-match") === o.httpEtag) delete o.body;
    const ims = options.onlyIf?.get?.("if-modified-since");
    if (ims && Math.floor(o.uploaded.getTime() / 1000) <= Math.floor(Date.parse(ims) / 1000)) delete o.body;
    return o;
  },
  async head(key) {
    const o = await this.get(key);
    if (o) delete o.body;
    return o;
  },
};
const env = { BUCKET };
const call = (path, init) => handle(new Request(`https://packages.grassfield.site${path}`, { redirect: "manual", ...init }), env);

// serve.py on a free port, the same tree.
let server, port;
test.before(async () => {
  port = 20000 + Math.floor(Math.random() * 20000);
  server = spawn("python3", ["-I", join(here, "..", "scripts", "serve.py"), root, String(port)], { stdio: "ignore" });
  for (let i = 0; i < 50; i++) {
    try { await fetch(`http://127.0.0.1:${port}/stable/x86_64/pointer`); return; } catch { await new Promise((r) => setTimeout(r, 100)); }
  }
  throw new Error("serve.py did not start");
});
test.after(() => { server?.kill(); rmSync(root, { recursive: true, force: true }); });

const ref = (path, init) => fetch(`http://127.0.0.1:${port}${path}`, { redirect: "manual", ...init });

test("fixed names: same status, Location and no-store as serve.py", async () => {
  for (const n of NAMES) {
    const [a, b] = [await call(`/stable/x86_64/${n}`), await ref(`/stable/x86_64/${n}`)];
    assert.equal(a.status, 302);
    assert.equal(a.status, b.status, n);
    assert.equal(a.headers.get("location"), b.headers.get("location"), n);
    assert.equal(a.headers.get("location"), `/stable/x86_64/snap/${SNAP}/${n}`);
    assert.equal(a.headers.get("cache-control"), "no-store");
    assert.equal(b.headers.get("cache-control"), "no-store");
  }
});

test("fixed names: a malformed, hostile or missing pointer is a 404, as serve.py", async () => {
  for (const p of ["/beta/x86_64/grassfield.db", "/stable/arm64/grassfield.db", "/stable/riscv/grassfield.db.sig"]) {
    const [a, b] = [await call(p), await ref(p)];
    assert.equal(a.status, 404, p);
    assert.equal(b.status, 404, p);
    assert.equal(a.headers.get("cache-control"), "no-store");
    assert.equal(a.headers.get("location"), null);
  }
});

test("a pointer moved: the next request follows it at once", async () => {
  put("stable/x86_64/pointer", JSON.stringify({ snapshot: OTHER }));
  const [a, b] = [await call("/stable/x86_64/grassfield.db"), await ref("/stable/x86_64/grassfield.db")];
  assert.equal(a.headers.get("location"), `/stable/x86_64/snap/${OTHER}/grassfield.db`);
  assert.equal(a.headers.get("location"), b.headers.get("location"));
  put("stable/x86_64/pointer", JSON.stringify({ snapshot: SNAP }));
});

test("HEAD on a fixed name redirects too; other methods are refused", async () => {
  const a = await call("/stable/x86_64/grassfield.db", { method: "HEAD" });
  assert.equal(a.status, 302);
  assert.equal((await call("/stable/x86_64/grassfield.db", { method: "POST" })).status, 405);
});

test("a query string does not change the rule (serve.py strips it)", async () => {
  const a = await call("/stable/x86_64/grassfield.db?x=1");
  assert.equal(a.status, 302);
});

test("other paths pass through to the bucket, immutable names cached for a year", async () => {
  const snapFile = `/stable/x86_64/snap/${SNAP}/grassfield.db`;
  const a = await call(snapFile);
  assert.equal(a.status, 200);
  assert.equal(await a.text(), "content of grassfield.db");
  assert.equal(a.headers.get("cache-control"), IMMUTABLE);
  assert.equal((await ref(snapFile)).status, 200);
  const pkg = await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst");
  assert.equal(pkg.headers.get("cache-control"), IMMUTABLE);
  assert.equal(await pkg.text(), "0123456789");
});

test("the pointer, the manifest listing and anything unknown are never cached", async () => {
  const p = await call("/stable/x86_64/pointer");
  assert.equal(p.status, 200);
  assert.equal(p.headers.get("cache-control"), NO_STORE);
  for (const k of ["stable/x86_64/pointer", "releases/stable/1.0.0/grassfield.db", "stable/x86_64/snap/a/b/c", "x"]) {
    assert.equal(cacheControlFor(k), NO_STORE, k);
  }
  assert.equal(cacheControlFor("stable/x86_64/catalog/" + "a".repeat(64) + ".png"), IMMUTABLE);
  assert.equal(cacheControlFor("beta/x86_64/a-1-1-any.pkg.tar.zst.sig"), IMMUTABLE);
});

test("4xx and 5xx are never cached; a missing object is 404; traversal is refused", async () => {
  for (const p of ["/stable/x86_64/nothing.pkg.tar.zst", `/stable/x86_64/snap/${SNAP}/missing`, "/", "/a/../b", "//x", "/%2e%2e/x"]) {
    const a = await call(p);
    assert.equal(a.status, 404, p);
    assert.equal(a.headers.get("cache-control"), "no-store", p);
  }
  assert.equal((await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst", { method: "POST" })).status, 405);
});

test("a range request is a 206 (pacman resumes downloads); a matching ETag is a 304 without a long cache", async () => {
  const r = await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst", { headers: { Range: "bytes=2-5" } });
  assert.equal(r.status, 206);
  assert.equal(await r.text(), "2345");
  assert.equal(r.headers.get("content-range"), "bytes 2-5/10");
  const full = await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst");
  const etag = full.headers.get("etag");
  const nm = await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst", { headers: { "If-None-Match": etag } });
  assert.equal(nm.status, 304);
  const h = await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst", { method: "HEAD" });
  assert.equal(h.status, 200);
  assert.equal(h.headers.get("content-length"), "10");
});

// A pointer switch with If-Modified-Since: pacman keeps the Last-Modified of what it downloaded as the file's mtime.
test("Last-Modified is sent, and If-Modified-Since across a pointer switch behaves as serve.py", async () => {
  const old = "20261101T000000Z-aaaaaaaaaaaa", fresh = "20261103T000000Z-bbbbbbbbbbbb";
  const t1 = 1793000000, t2 = 1793100000; // seconds: the new snapshot is uploaded later
  for (const [id, t] of [[old, t1], [fresh, t2]]) {
    put(`stable/x86_64/snap/${id}/grassfield.db`, `db ${id}`);
    utimesSync(join(root, `stable/x86_64/snap/${id}/grassfield.db`), t, t);
  }
  const fixed = "/stable/x86_64/grassfield.db";
  const lm = {};
  for (const [label, id] of [["old", old], ["fresh", fresh]]) {
    const p = `/stable/x86_64/snap/${id}/grassfield.db`;
    const [a, b] = [await call(p), await ref(p)];
    assert.equal(a.status, 200);
    assert.ok(a.headers.get("last-modified"), "Last-Modified on the worker");
    assert.equal(a.headers.get("last-modified"), b.headers.get("last-modified"), label);
    lm[label] = a.headers.get("last-modified");
  }
  // The client holds the old database (mtime = its Last-Modified); the pointer now names the fresh one.
  put("stable/x86_64/pointer", JSON.stringify({ snapshot: fresh }));
  const h = { "If-Modified-Since": lm.old };
  // the redirect is never conditional: serve.py answers 302 whatever the client sends
  const [ra, rb] = [await call(fixed, { headers: h }), await ref(fixed, { headers: h })];
  assert.equal(ra.status, 302);
  assert.equal(rb.status, 302);
  assert.equal(ra.headers.get("location"), rb.headers.get("location"));
  // its target is newer than the client's copy: 200 with the new content, on both
  const path = new URL(ra.headers.get("location"), "https://x").pathname;
  const [ta, tb] = [await call(path, { headers: h }), await ref(path, { headers: h })];
  assert.equal(ta.status, 200);
  assert.equal(tb.status, 200);
  assert.equal(await ta.text(), `db ${fresh}`);
  // a client already holding the fresh one: 304 on the target, still 302 on the fixed name, on both
  const h2 = { "If-Modified-Since": lm.fresh };
  assert.equal((await call(path, { headers: h2 })).status, 304);
  assert.equal((await ref(path, { headers: h2 })).status, 304);
  assert.equal((await call(fixed, { headers: h2 })).status, 302);
  assert.equal((await ref(fixed, { headers: h2 })).status, 302);
  // a pass-through object carries Last-Modified too
  assert.ok((await call("/stable/x86_64/pkg-1.0-1-x86_64.pkg.tar.zst")).headers.get("last-modified"));
  put("stable/x86_64/pointer", JSON.stringify({ snapshot: SNAP }));
});
