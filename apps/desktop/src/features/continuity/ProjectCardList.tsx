import { FolderKanban, MoveRight } from "lucide-react";
import type { VisibleContinuityProjectCard } from "./visibleContinuityTypes";

type ProjectCardListProps = {
  projects: VisibleContinuityProjectCard[];
};

export function ProjectCardList({ projects }: ProjectCardListProps) {
  if (projects.length === 0) {
    return (
      <section className="visible-continuity-section" aria-label="任务线索">
        <SectionTitle />
        <p className="visible-continuity-muted">当任务、日记或记忆反复提到同一条线索后，这里会出现任务卡片。</p>
      </section>
    );
  }

  return (
    <section className="visible-continuity-section" aria-label="任务线索">
      <SectionTitle />
      <div className="visible-continuity-project-list">
        {projects.map((project) => (
          <article key={project.project_id} className="visible-continuity-project">
            <div className="visible-continuity-item-head">
              <strong>{project.title}</strong>
              <span>{project.current_state}</span>
            </div>
            <p>{project.recent_progress}</p>
            <div className="visible-continuity-next-step">
              <MoveRight size={15} aria-hidden="true" />
              <span>{project.next_step}</span>
            </div>
            {project.blockers.length > 0 ? (
              <ul className="visible-continuity-blockers">
                {project.blockers.map((blocker) => (
                  <li key={blocker}>{blocker}</li>
                ))}
              </ul>
            ) : null}
            <footer className="visible-continuity-meta">
              <span>{project.sources.length} 条来源</span>
              {project.last_touched_at ? (
                <time dateTime={project.last_touched_at}>{formatDate(project.last_touched_at)}</time>
              ) : null}
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}

function SectionTitle() {
  return (
    <div className="visible-continuity-section-head compact">
      <FolderKanban size={18} aria-hidden="true" />
      <div>
        <h3>任务线索</h3>
        <p>从本地记录中反复出现的主题，整理出当前状态和下一步。</p>
      </div>
    </div>
  );
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
  });
}
