import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 서버 5180. /api 는 Spring Boot(8080)로 프록시하므로 CORS 설정이 필요 없다.
// fs.allow: 실측 결과(results/summary.json)와 차트(docs/charts)를 프로젝트 루트에서 직접 import 한다.
export default defineConfig({
  plugins: [react()],
  server: { port: 5180, proxy: { '/api': 'http://localhost:8080' }, fs: { allow: ['..'] } },
})
