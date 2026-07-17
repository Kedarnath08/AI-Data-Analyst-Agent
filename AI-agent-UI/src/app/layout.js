import "./globals.css";

export const metadata = {
  title: "RAG Chat UI",
  description: "Gemini + Pinecone frontend",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
