import { readFileSync, readdirSync } from "node:fs";
import { basename, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const appShellPath = resolve(__dirname, "AppShell.tsx");
const appShellDirectory = resolve(__dirname, "appShell");
const orchestrationPaths = [
  appShellPath,
  ...readdirSync(appShellDirectory)
    .filter((fileName) => /\.tsx?$/.test(fileName))
    .sort()
    .map((fileName) => resolve(appShellDirectory, fileName)),
];
const orchestrationSources = new Map(
  orchestrationPaths.map((filePath) => [filePath, readFileSync(filePath, "utf8")]),
);
const appShellSource = orchestrationSources.get(appShellPath)!;
const eslintConfig = readFileSync(resolve(__dirname, "../.eslintrc.cjs"), "utf8");

function parseSource(filePath: string, source: string): ts.SourceFile {
  return ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

function appShellHookCount(): number {
  const sourceFile = parseSource(appShellPath, appShellSource);
  const appShell = sourceFile.statements.find(
    (statement): statement is ts.FunctionDeclaration =>
      ts.isFunctionDeclaration(statement) && statement.name?.text === "AppShell",
  );
  if (!appShell?.body) {
    throw new Error("Missing AppShell function declaration");
  }

  let count = 0;
  const visit = (node: ts.Node) => {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      /^use[A-Z]/.test(node.expression.text)
    ) {
      count += 1;
    }
    ts.forEachChild(node, visit);
  };
  visit(appShell.body);
  return count;
}

type ComponentBoundary = {
  componentName: string;
  fileName: string;
  propCount: number;
};

function componentBoundaries(): ComponentBoundary[] {
  const boundaries: ComponentBoundary[] = [];
  for (const [filePath, source] of orchestrationSources) {
    const sourceFile = parseSource(filePath, source);
    const visit = (node: ts.Node) => {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const componentName = node.tagName.getText(sourceFile);
        if (/^[A-Z]/.test(componentName)) {
          boundaries.push({
            componentName,
            fileName: basename(filePath),
            propCount: node.attributes.properties.length,
          });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }
  return boundaries;
}

describe("AppShell architecture contract", () => {
  it("keeps the renderer orchestrator within its line and hook limits", () => {
    expect(appShellSource.split(/\r?\n/).length).toBeLessThanOrEqual(300);
    expect(appShellHookCount()).toBeLessThanOrEqual(15);
  });

  it("keeps every current AppShell child boundary at twelve top-level props or fewer", () => {
    const boundaries = componentBoundaries();
    const componentNames = boundaries.map((boundary) => boundary.componentName);
    for (const expectedBoundary of [
      "AgentActivityEntryRenderer",
      "ConnectionManagementPanel",
      "ControlDashboard",
      "DesktopFeatureRoutes",
      "PetWindow",
      "SettingsPanel",
      "StageView",
      "WikiManagementPanels",
    ]) {
      expect(componentNames).toContain(expectedBoundary);
    }
    for (const boundary of boundaries) {
      expect(
        boundary.propCount,
        `${boundary.fileName}: <${boundary.componentName}> has ${boundary.propCount} top-level props`,
      ).toBeLessThanOrEqual(12);
    }
  });

  it("forbids the former settings counter and browser-native destructive confirmation", () => {
    const source = [...orchestrationSources.values()].join("\n");
    expect(source).not.toContain("pendingSettingsStatusVersion");
    expect(source).not.toContain("window.confirm");
  });

  it("enables exhaustive hook dependency checking as an error without local opt-outs", () => {
    expect(eslintConfig).toContain('"react-hooks/exhaustive-deps": "error"');
    for (const source of orchestrationSources.values()) {
      expect(source).not.toMatch(/eslint-disable(?:-next-line)?\s+react-hooks\//);
    }
  });
});
