import type { ReactNode } from "react";

type PageLayoutProps = {
  header: ReactNode;
  filters: ReactNode;
  slate: ReactNode;
  content: ReactNode;
  injuries?: ReactNode;
};

export function PageLayout({ header, filters, slate, content, injuries }: PageLayoutProps) {
  return (
    <main className="page">
      <section className="app-header">{header}</section>
      <section className="panel filter-bar">{filters}</section>
      <section className="panel slate-panel">{slate}</section>
      <section className="panel data-panel">{content}</section>
      {injuries ? <section className="panel injuries">{injuries}</section> : null}
    </main>
  );
}
