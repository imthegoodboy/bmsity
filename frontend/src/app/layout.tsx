import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BmsitAi | AI Exam Evaluation Portal",
  description: "BMSIT&M AI answer sheet evaluation for teachers and students",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html data-scroll-behavior="smooth" lang="en">
      <body>{children}</body>
    </html>
  );
}
