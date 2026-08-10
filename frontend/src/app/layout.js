import "./globals.css";

export const metadata = {
  title: "MeetingMind — AI Meeting Minutes Generator",
  description:
    "Upload meeting recordings and get AI-powered meeting minutes with speaker diarization, executive summaries, and action items.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
