/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a self-contained server bundle so the Docker image doesn't need the
  // full node_modules tree at runtime.
  output: "standalone",
};

export default nextConfig;
