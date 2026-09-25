import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import "../styles/camera.css"

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'https://websocket-inzynierka.onrender.com').replace(/\/$/, '')

const websocketUrl = (path, token) => {
    const url = new URL(API_BASE_URL)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.pathname = path
    url.search = new URLSearchParams({ token }).toString()
    return url.toString()
}

export const Camera = () => {

    const videoRef = useRef(null)
    const canvasRef = useRef(null)
    const wsRef = useRef(null)
    const streamRef = useRef(null)
    const encodingRef = useRef(false)
    const [stream, setStream] = useState(null)
    const [error, setError] = useState(null)
    const [session, setSession] = useState(null)
    const [connectingStatus, setConnectingStatus] = useState('connecting...')
    const [peers, setPeers] = useState({ python: false, unity: false })
    const [source, setSource] = useState('')

    const stopCamera = useCallback(() => {
        const activeStream = streamRef.current
        if (activeStream) {
            activeStream.getTracks().forEach(track => track.stop())
        }
        streamRef.current = null
        setStream(null)
        if (videoRef.current) {
            videoRef.current.srcObject = null
        }
    }, [])

    useEffect(() => {
        const controller = new AbortController()

        const createSession = async () => {
            try {
                const stored = sessionStorage.getItem('manipulatorSession')
                if (stored) {
                    const restoredSession = JSON.parse(stored)
                    if (restoredSession?.code && restoredSession?.browserToken) {
                        setSession(restoredSession)
                        return restoredSession
                    }
                }
                const options = {
                    method: 'POST',
                    signal: controller.signal,
                }
                const response = await fetch(`${API_BASE_URL}/api/sessions`, options)
                if (!response.ok) throw new Error(`Failed to create session: ${response.status} ${response.statusText}`)
                const createdSession = await response.json()
                sessionStorage.setItem('manipulatorSession', JSON.stringify(createdSession))
                setSession(createdSession)
            } catch (err) {
                if (err.name != 'AbortError') {
                    setConnectingStatus('Failed to create session')
                    setError(err)
                }
            }
        }

        createSession()
        return () => controller.abort()
    }, [])

    useEffect(() => {
        if (!session) return undefined

        const socket = new WebSocket(websocketUrl('/ws/browser', session.browserToken))
        wsRef.current = socket
        setConnectingStatus('connecting...')

        socket.onopen = () => setConnectingStatus('connected')
        socket.onmessage = (e) => {
            if (typeof e.data !== 'string') return
            try {
                const message = JSON.parse(e.data)
                if (message.type === 'status') {
                    setPeers({ python: Boolean(message.python), unity: Boolean(message.unity) })
                    setSource(message.source || '')
                }
            } catch (err) {
                setError("Failed to parse message from server")
            }
        }
    }, [session])

    useEffect(() => {
        if (source !== 'remote_camera' || connectingStatus !== 'connected') {
            stopCamera()
        }
    }, [source, connectingStatus, stopCamera])

    const startCamera = async () => {
        setError(null)
        try {
            const mediaStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: 'environment',
                    width: { ideal: 640 },
                    height: { ideal: 480 }
                }
            })
            streamRef.current = mediaStream
            setStream(mediaStream)
            if (videoRef.current) {
                videoRef.current.srcObject = mediaStream
            }
        } catch {
            setError('Failed to access camera')
        }
    }

    useEffect(() => {
        if (!stream && source !== 'remote_camera') return undefined

        const interval = setInterval(() => {
            const socket = wsRef.current
            const video = videoRef.current
            const canvas = canvasRef.current
            if (encodingRef.current || !video || !canvas || socket?.readyState !== WebSocket.OPEN) return
            if (!video.videoWidth || !video.videoHeight) return

            encodingRef.current = true
            canvas.width = 640
            canvas.height = 480
            canvas.getContext('2d').drawImage(video, 0, 0, 640, 480)
            canvas.toBlob((blob) => {
                try {
                    if (blob && blob.size <= 200 * 1024 && socket.readyState === WebSocket.OPEN) socket.send(blob)
                } finally {
                    encodingRef.current = false
                }
            }, 'image/jpeg', 0.7)
        }, 100)
        
        return () => {
            clearInterval(interval)
            encodingRef.current = false
        } 
    }, [stream, source])

    const webCameraReady = peers.python && source === 'remote_camera' && connectingStatus === 'connected'
    const expiresAt = session ? new Date(session.expiresAt).toLocaleString('pl-PL', { hour: '2-digit', minute: '2-digit' }) : '-'
    
    return (
        <>
            <main className="camera-page">
                <header className="camera-header">
                    <div>
                        <span className="eyebrow">Transmisja obrazu</span>
                        <h1>Kamera sterująca</h1>
                        <p>Przekaż obraz do lokalnego systemu analizy gestów.</p>
                    </div>
                    <div className={`connection-status connection-status--${connectingStatus}`} role="status">
                        <span className="connection-status__dot" aria-hidden="true" />
                        {connectingStatus === 'connected'
                            ? 'Serwer połączony'
                            : connectingStatus === 'connecting'
                                ? 'Łączenie z serwerem…'
                                : 'Serwer rozłączony'}
                    </div>
                </header>

                <section className="session-panel" aria-label="Dane sesji">
                    <div>
                        <span className="session-panel__label">Kod sesji</span>
                        <strong className="session-panel__code">{session?.code || '…'}</strong>
                        <span className="session-panel__expiry">Ważny do {expiresAt}</span>
                    </div>
                    <div className="session-panel__clients">
                        <span className={peers.python ? 'client-state is-online' : 'client-state'}>
                            <i /> Python {peers.python ? 'połączony' : 'oczekuje'}
                        </span>
                        <span className={peers.unity ? 'client-state is-online' : 'client-state'}>
                            <i /> Unity {peers.unity ? 'połączone' : 'oczekuje'}
                        </span>
                    </div>
                </section>

                <section className="camera-workspace" aria-label="Panel kamery">
                    <aside className="camera-controls">
                        <div className="camera-controls__heading">
                            <span className="camera-controls__step">01</span>
                            <div>
                                <h2>Sterowanie</h2>
                                <p>Wpisz kod w Pythonie i wybierz tam źródło obrazu.</p>
                            </div>
                        </div>

                        <div className="source-summary">
                            <span>Wybrane źródło</span>
                            <strong>
                                {source === 'remote_camera' ? 'Kamera webowa' : source === 'local_camera' ? 'Kamera lokalna' : 'Oczekiwanie na Python'}
                            </strong>
                        </div>

                        <div className="camera-controls__actions">
                            {!stream ? (
                                <button className="button button--primary" onClick={startCamera} disabled={!webCameraReady}>
                                    Uruchom kamerę
                                </button>
                            ) : (
                                <button className="button button--danger" onClick={stopCamera}>Zatrzymaj kamerę</button>
                            )}
                        </div>

                        {!webCameraReady && !error && (
                            <p className="camera-notice">
                                {source === 'local_camera'
                                    ? 'Obraz jest analizowany bezpośrednio z kamery przy aplikacji Python.'
                                    : 'Połącz aplikację Python i wybierz w niej kamerę webową.'}
                            </p>
                        )}
                        {error && <p className="camera-error" role="alert"><span aria-hidden="true">!</span>{error}</p>}

                        <div className="camera-help">
                            <h3>Wskazówki</h3>
                            <ul>
                                <li>Zadbaj o równomierne oświetlenie.</li>
                                <li>Trzymaj całą dłoń w obszarze kamery.</li>
                                <li>Nie zasłaniaj palców podczas ruchu.</li>
                            </ul>
                        </div>
                    </aside>

                    <div className={`camera-preview ${stream ? 'camera-preview--active' : ''}`}>
                        <div className="camera-preview__topbar">
                            <span>Podgląd na żywo</span>
                            <span className={`camera-state ${stream ? 'camera-state--active' : ''}`}>{stream ? 'Aktywna' : 'Nieaktywna'}</span>
                        </div>
                        <div className="camera-preview__viewport">
                            <video ref={videoRef} autoPlay playsInline className={`camera-preview__video ${stream ? 'is-visible' : ''}`} />
                            <canvas ref={canvasRef} className="visually-hidden-canvas" />
                            {!stream && (
                                <div className="camera-placeholder">
                                    <div className="camera-placeholder__icon" aria-hidden="true"><span /></div>
                                    <h2>Kamera jest wyłączona</h2>
                                    <p>{source === 'local_camera' ? 'Aktywna jest kamera lokalna aplikacji Python.' : 'Uruchom kamerę po sparowaniu aplikacji Python.'}</p>
                                </div>
                            )}
                        </div>
                    </div>
                </section>

                <Link className="camera-back-link" to="/"><span aria-hidden="true">←</span>Powrót do strony głównej</Link>
            </main>
        </>
    )
}