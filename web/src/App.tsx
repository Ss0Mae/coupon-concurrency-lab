import { useEffect, useState } from 'react'
import { api } from './api'
import Live from './Live'
import Results from './Results'

export default function App() {
  const [appUp, setAppUp] = useState<boolean | null>(null)
  useEffect(() => {
    api.state().then(() => setAppUp(true)).catch(() => setAppUp(false))
  }, [])

  return (
    <main className="page">
      <header className="masthead">
        <div>
          <h1>쿠폰 동시성 실험실</h1>
          <p className="lede">
            쿠폰 100장에 1,000명이 동시에 요청하면 어떤 구현이 정확히 100장만 나눠 주는지, 같은 조건으로 직접 실행해 확인합니다.
            아래 수치는 실행 버튼을 누른 순간 이 컴퓨터의 MySQL 에서 실제로 일어난 결과입니다.
          </p>
        </div>
        <nav className="services" aria-label="연결된 서비스">
          <span><i className={'dot ' + (appUp == null ? '' : appUp ? 'up' : 'down')} />발급 API 8080</span>
          <a href="http://localhost:3000/d/coupon-lab" target="_blank" rel="noreferrer">Grafana 3000</a>
          <a href="http://localhost:9090" target="_blank" rel="noreferrer">Prometheus 9090</a>
          <a href="http://localhost:8080/actuator/prometheus" target="_blank" rel="noreferrer">메트릭 원본</a>
        </nav>
      </header>
      <Live appUp={appUp} onAppStatus={setAppUp} />
      <Results />
    </main>
  )
}
