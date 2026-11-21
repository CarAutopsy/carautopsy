import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CarAutopsy — True Cost of Ownership, Austria",
  description:
    "Transparent, attested total cost of ownership for vehicles in Austria, calculated from statutory tax rules.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
