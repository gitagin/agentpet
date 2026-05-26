import type { ReactNode } from "react";

export function Panel({
  id,
  title,
  icon,
  className = "",
  children,
}: {
  id?: string;
  title: string;
  icon: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={`panel ${className}`}>
      <div className="panel-title">
        {icon}
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}
