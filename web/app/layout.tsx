import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import TopNav from "@/components/TopNav";

const inter = Inter({ variable: "--font-inter", subsets: ["latin", "cyrillic"] });

export const metadata: Metadata = {
  title: "MedRate — поиск цен на медицинские услуги",
  description:
    "Единая база прайсов клиник-партнёров: найдите, кто оказывает услугу и по какой цене — для резидентов и нерезидентов.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-900">
        <TopNav />
        <main className="flex-1">{children}</main>
        <footer className="border-t border-slate-200 py-6 text-center text-sm text-slate-400">
          MedRate · единая база прайсов клиник-партнёров
        </footer>
      </body>
    </html>
  );
}
