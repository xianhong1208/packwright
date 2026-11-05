/**
 * Packwright's mark: a P whose bowl closes like a box flap folded shut. Drawn in
 * currentColor so it sits on the brass tile of the rail and the sign-in page;
 * public/mark.svg is the same shape with the tile, for the browser tab.
 */
export default function Mark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="6 4 20 24" aria-hidden="true" fill="none" stroke="currentColor">
      <path d="M11 25V7h7.5a5.5 5.5 0 0 1 0 11H11" strokeWidth={3.2} strokeLinejoin="round" />
      <path d="M11 18l6.5 0 -3 -3.5" strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
