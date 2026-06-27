export default function VerifiedBadge({ verified }: { verified: number | boolean }) {
  if (verified) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-700 ring-1 ring-teal-200">
        ✓ Проверено
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 ring-1 ring-slate-200">
      на проверке
    </span>
  );
}
