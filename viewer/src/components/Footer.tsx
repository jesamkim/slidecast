// Small attribution line shown on the gallery and login screens (not on the
// fullscreen playback/public surfaces, where it would overlap slide content).
export function Footer() {
  return (
    <footer
      style={{
        textAlign: "center",
        padding: "24px 16px 20px",
        fontSize: 12.5,
        letterSpacing: "0.01em",
        color: "var(--text-dim)",
        opacity: 0.6,
      }}
    >
      Crafted with vibes by jesamkim · © 2026
    </footer>
  );
}
