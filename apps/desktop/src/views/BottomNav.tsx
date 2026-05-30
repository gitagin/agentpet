import {
  openPrimaryNavigationTab,
  primaryNavigationTabs,
  type PrimaryNavigationTab,
} from "./navigation";

export function BottomNav({ activeTab }: { activeTab: PrimaryNavigationTab }) {
  return (
    <nav className="bottom-nav" aria-label="主导航">
      <span
        aria-hidden="true"
        className="bottom-nav-indicator"
        style={{ transform: `translateX(${primaryNavigationTabs.indexOf(activeTab) * 62}px)` }}
      />
      {primaryNavigationTabs.map((tab) => (
        <button
          key={tab}
          type="button"
          className={`bottom-nav-button${tab === activeTab ? " active" : ""}`}
          onClick={() => openPrimaryNavigationTab(tab)}
        >
          {tab}
        </button>
      ))}
    </nav>
  );
}
