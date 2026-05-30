import type { ReactNode } from "react";

export function FeatureWindowShell({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <main className="feature-shell">
      <header className="feature-window-header">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <section className="feature-window-content">{children}</section>
    </main>
  );
}
