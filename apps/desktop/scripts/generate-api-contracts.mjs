import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const DESKTOP_DIR = resolve(SCRIPT_DIR, "..");

export const ARTIFACT_SCHEMA_VERSION = 1;
export const EXEMPTIONS_SCHEMA_VERSION = 1;
export const OPENAPI_OPERATION_METHODS = Object.freeze([
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "HEAD",
  "OPTIONS",
  "TRACE",
]);
export const RENDERER_PROXY_METHODS = Object.freeze(["GET", "POST", "PUT", "PATCH", "DELETE"]);

export const DEFAULT_PATHS = Object.freeze({
  openapi: resolve(DESKTOP_DIR, "..", "backend", "openapi.json"),
  exemptions: resolve(DESKTOP_DIR, "electron", "proxy-route-exemptions.json"),
  proxyRoutes: resolve(DESKTOP_DIR, "electron", "proxy-routes.generated.json"),
  types: resolve(DESKTOP_DIR, "src", "types.gen.ts"),
});

function normalizedText(text) {
  return text.replace(/\r\n/g, "\n");
}

function routeKey(method, path) {
  return `${method} ${path}`;
}

function assertPlainObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
}

export function collectOpenApiRoutes(schema) {
  assertPlainObject(schema, "OpenAPI document");
  assertPlainObject(schema.paths, "OpenAPI paths");

  const operationMethods = new Set(OPENAPI_OPERATION_METHODS.map((method) => method.toLowerCase()));
  const routes = [];
  for (const path of Object.keys(schema.paths).sort()) {
    if (!path.startsWith("/api/")) {
      continue;
    }
    const pathItem = schema.paths[path];
    assertPlainObject(pathItem, `OpenAPI path item ${path}`);
    for (const method of Object.keys(pathItem).sort()) {
      if (operationMethods.has(method.toLowerCase())) {
        routes.push({ method: method.toUpperCase(), path });
      }
    }
  }
  return routes;
}

export function collectExemptions(document, declaredRoutes) {
  assertPlainObject(document, "Proxy route exemptions");
  if (document.schemaVersion !== EXEMPTIONS_SCHEMA_VERSION) {
    throw new Error(
      `Unsupported proxy exemption schemaVersion ${String(document.schemaVersion)}; expected ${EXEMPTIONS_SCHEMA_VERSION}.`,
    );
  }
  if (!Array.isArray(document.routes)) {
    throw new Error("Proxy route exemptions routes must be an array.");
  }

  const declaredKeys = new Set(declaredRoutes.map((route) => routeKey(route.method, route.path)));
  const seen = new Set();
  return document.routes.map((entry, index) => {
    assertPlainObject(entry, `Proxy route exemption at index ${index}`);
    const method = typeof entry.method === "string" ? entry.method.toUpperCase() : "";
    const path = typeof entry.path === "string" ? entry.path : "";
    const reason = typeof entry.reason === "string" ? entry.reason.trim() : "";
    if (!OPENAPI_OPERATION_METHODS.includes(method) || !path.startsWith("/api/") || !reason) {
      throw new Error(`Invalid proxy route exemption at index ${index}; method, /api/ path, and reason are required.`);
    }
    const key = routeKey(method, path);
    if (seen.has(key)) {
      throw new Error(`Duplicate proxy route exemption: ${key}.`);
    }
    if (!declaredKeys.has(key)) {
      throw new Error(`Stale proxy route exemption does not exist in OpenAPI: ${key}.`);
    }
    seen.add(key);
    return { method, path, reason };
  });
}

export function buildProxyRouteArtifact({ schema, openapiText, exemptionsDocument }) {
  const declaredRoutes = collectOpenApiRoutes(schema);
  if (declaredRoutes.length === 0) {
    throw new Error("OpenAPI contains no /api/ operations; refusing to generate an empty renderer proxy allowlist.");
  }
  const exemptions = collectExemptions(exemptionsDocument, declaredRoutes);
  const exemptKeys = new Set(exemptions.map((route) => routeKey(route.method, route.path)));
  const supportedMethods = new Set(RENDERER_PROXY_METHODS);

  const unsupported = declaredRoutes.filter(
    (route) => !supportedMethods.has(route.method) && !exemptKeys.has(routeKey(route.method, route.path)),
  );
  if (unsupported.length > 0) {
    throw new Error(
      "OpenAPI contains methods unsupported by the renderer proxy. Extend the proxy or add justified exemptions:\n" +
        unsupported.map((route) => `  ${route.method} ${route.path}`).join("\n"),
    );
  }

  const methodsByPath = new Map();
  for (const route of declaredRoutes) {
    if (exemptKeys.has(routeKey(route.method, route.path))) {
      continue;
    }
    const methods = methodsByPath.get(route.path) ?? [];
    methods.push(route.method);
    methodsByPath.set(route.path, methods);
  }

  return {
    schemaVersion: ARTIFACT_SCHEMA_VERSION,
    source: {
      openapiVersion: schema.openapi,
      apiVersion: schema.info?.version,
      sha256: createHash("sha256").update(normalizedText(openapiText), "utf8").digest("hex"),
    },
    routes: [...methodsByPath.entries()]
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([path, methods]) => ({ path, methods: methods.sort() })),
  };
}

export function renderProxyRouteArtifact(artifact) {
  return `${JSON.stringify(artifact, null, 2)}\n`;
}

async function renderGeneratedTypes(schema) {
  const ast = await openapiTS(schema);
  return COMMENT_HEADER + astToString(ast);
}

function parseArguments(argv) {
  const flags = new Set(argv);
  const known = new Set(["--check", "--proxy-only", "--types-only"]);
  const unknown = [...flags].filter((flag) => !known.has(flag));
  if (unknown.length > 0) {
    throw new Error(`Unknown argument(s): ${unknown.join(", ")}`);
  }
  if (flags.has("--proxy-only") && flags.has("--types-only")) {
    throw new Error("--proxy-only and --types-only cannot be combined.");
  }
  return {
    check: flags.has("--check"),
    proxy: !flags.has("--types-only"),
    types: !flags.has("--proxy-only"),
  };
}

function verifyOrWrite(path, expected, check) {
  if (!check) {
    writeFileSync(path, expected, "utf8");
    return false;
  }
  let actual = "";
  try {
    actual = normalizedText(readFileSync(path, "utf8"));
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
  return actual !== normalizedText(expected);
}

export async function generateApiContracts({ argv = process.argv.slice(2), paths = DEFAULT_PATHS } = {}) {
  const options = parseArguments(argv);
  const openapiText = readFileSync(paths.openapi, "utf8");
  const schema = JSON.parse(openapiText);
  const stale = [];

  if (options.proxy) {
    const exemptionsDocument = JSON.parse(readFileSync(paths.exemptions, "utf8"));
    const artifact = buildProxyRouteArtifact({ schema, openapiText, exemptionsDocument });
    if (verifyOrWrite(paths.proxyRoutes, renderProxyRouteArtifact(artifact), options.check)) {
      stale.push(paths.proxyRoutes);
    }
  }
  if (options.types) {
    const generatedTypes = await renderGeneratedTypes(schema);
    if (verifyOrWrite(paths.types, generatedTypes, options.check)) {
      stale.push(paths.types);
    }
  }

  if (stale.length > 0) {
    throw new Error(
      `Generated API contracts are stale:\n${stale.map((path) => `  ${path}`).join("\n")}\n` +
        "Run `npm run generate:api-contracts` from apps/desktop and commit the results.",
    );
  }
  return { options, paths };
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  generateApiContracts()
    .then(({ options }) => {
      const verb = options.check ? "verified" : "generated";
      console.log(`OpenAPI-derived desktop contracts ${verb}.`);
    })
    .catch((error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    });
}
