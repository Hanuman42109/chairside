import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/calls", label: "Calls" },
  { to: "/eval-results", label: "Eval Results" },
];

function navLinkClasses(isActive: boolean): string {
  const base = "block rounded-md px-3 py-2 text-sm font-medium transition-colors";
  return isActive
    ? `${base} bg-slate-900 text-white`
    : `${base} text-slate-600 hover:bg-slate-100 hover:text-slate-900`;
}

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white p-4">
        <div className="mb-6 px-2 text-lg font-semibold text-slate-900">Chairside</div>
        <nav className="space-y-1">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => navLinkClasses(isActive)}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-8">{children}</main>
    </div>
  );
}
