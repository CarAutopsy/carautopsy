import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CarAutopsy — True Cost of Ownership",
  description: "Understand the true cost of owning a vehicle in Austria.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
