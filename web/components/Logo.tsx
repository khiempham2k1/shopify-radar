export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" aria-hidden="true">
      <circle cx="13" cy="13" r="11.5" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
      <circle cx="13" cy="13" r="6.5" fill="none" stroke="var(--accent)" strokeWidth="1.2" opacity=".55" />
      <path d="M13 13 L22 7" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="18.5" cy="16" r="1.8" fill="var(--crit)" />
    </svg>
  );
}
