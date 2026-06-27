"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PUBLIC_LINKS = [
  { href: "/", label: "Поиск услуг" },
  { href: "/partners", label: "Клиники" },
];

const ADMIN_LINKS = [
  { href: "/admin", label: "Дашборд" },
  { href: "/admin/verify", label: "Верификация" },
  { href: "/admin/unmatched", label: "Сопоставление" },
  { href: "/admin/upload", label: "Загрузка" },
];

export default function TopNav() {
  const pathname = usePathname();
  const inAdmin = pathname.startsWith("/admin");
  const links = inAdmin ? ADMIN_LINKS : PUBLIC_LINKS;

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 text-lg font-bold text-teal-700">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-teal-600 text-white">＋</span>
          MedRate
        </Link>

        <nav className="hidden gap-1 sm:flex">
          {links.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  active ? "bg-teal-50 text-teal-700" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto">
          <Link
            href={inAdmin ? "/" : "/admin"}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${
              inAdmin
                ? "text-slate-600 hover:bg-slate-100"
                : "bg-slate-900 text-white hover:bg-slate-700"
            }`}
          >
            {inAdmin ? "← На сайт" : "Кабинет оператора"}
          </Link>
        </div>
      </div>
    </header>
  );
}
