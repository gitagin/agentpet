const { readFileSync } = require("node:fs");

const generatorPromise = import("../scripts/generate-api-contracts.mjs");

function syntheticSchema() {
  return {
    openapi: "3.1.0",
    info: { title: "Synthetic API", version: "1.0.0" },
    paths: {
      "/api/public": { get: { responses: {} } },
      "/api/internal": { post: { responses: {} } },
    },
  };
}

describe("OpenAPI proxy route generation", () => {
  it("generates renderer routes while honoring explicit justified exemptions", async () => {
    const { buildProxyRouteArtifact } = await generatorPromise;
    const schema = syntheticSchema();
    const artifact = buildProxyRouteArtifact({
      schema,
      openapiText: JSON.stringify(schema),
      exemptionsDocument: {
        schemaVersion: 1,
        routes: [{ method: "POST", path: "/api/internal", reason: "Main-process maintenance only." }],
      },
    });

    expect(artifact.routes).toEqual([{ path: "/api/public", methods: ["GET"] }]);
  });

  it("rejects stale or unjustified exemptions instead of hiding route drift", async () => {
    const { buildProxyRouteArtifact } = await generatorPromise;
    const schema = syntheticSchema();

    expect(() =>
      buildProxyRouteArtifact({
        schema,
        openapiText: JSON.stringify(schema),
        exemptionsDocument: {
          schemaVersion: 1,
          routes: [{ method: "DELETE", path: "/api/missing", reason: "No longer exists." }],
        },
      }),
    ).toThrowError(/Stale proxy route exemption/);
    expect(() =>
      buildProxyRouteArtifact({
        schema,
        openapiText: JSON.stringify(schema),
        exemptionsDocument: {
          schemaVersion: 1,
          routes: [{ method: "POST", path: "/api/internal", reason: "" }],
        },
      }),
    ).toThrowError(/reason are required/);
  });

  it("keeps the committed proxy artifact and generated TypeScript synchronized", async () => {
    const { generateApiContracts } = await generatorPromise;

    await expect(generateApiContracts({ argv: ["--check"] })).resolves.toBeTruthy();
    expect(readFileSync(require.resolve("./proxy-routes.generated.json"), "utf8")).toContain(
      '"schemaVersion": 1',
    );
  });
});
