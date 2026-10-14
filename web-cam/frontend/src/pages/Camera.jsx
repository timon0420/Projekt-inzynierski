import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import "../styles/camera.css"

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'https://test-ws-7v80.onrender.com').replace(/\/$/, '')

const SESSION_STORAGE_KEY = 'manipulatorSession'
const DEFAULT_PATHS = { video: '/ws/video/browser', angles: '/ws/angles/browser' }
const FRAME_INTERVAL_MS = 110        
const MAX_FRAME_BYTES = 200 * 1024   
const MAX_BUFFERED_BYTES = 256 * 1024
const MAX_FAILED_ATTEMPTS = 3        
const NO_PEERS = { python: false, unity: false }

const websocketUrl = (path, token) => {
    const url = new URL(API_BASE_URL)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.pathname = path
    url.search = new URLSearchParams({ token }).toString()
    return url.toString()
}

const restoreSession = () => {
    try {
        const stored = JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY) || 'null')
        const expiresAt = Date.parse(stored?.expiresAt || '')
        if (stored?.code && stored?.browserToken && Number.isFinite(expiresAt) && expiresAt > Date.now()) {
            return stored
        }
    } catch {
        // Uszkodzone dane: utworzymy nową sesję.
    }
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
    return null
}

const requestSession = async (signal) => {
    const attempts = 4
    let lastError
    for (let attempt = 1; attempt <= attempts; attempt++) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/sessions`, { method: 'POST', signal })
            if (response.ok) return await response.json()
            const error = new Error(`Failed to create session: ${response.status} ${response.statusText}`)
            if (![502, 503, 504].includes(response.status)) {
                error.fatal = true
                throw error
            }
            lastError = error
        } catch (err) {
            if (err.name === 'AbortError' || err.fatal) throw err
            lastError = err
        }
        if (attempt < attempts) await new Promise(resolve => setTimeout(resolve, 3000))
    }
    throw lastError
}

const useChannel = (url, onMessage, onSessionLost) => {
    const [state, setState] = useState('connecting')
    const socketRef = useRef(null)
    const handlersRef = useRef({ onMessage, onSessionLost })
    handlersRef.current = { onMessage, onSessionLost }

    useEffect(() => {
        if (!url) return undefined

        let disposed = false
        let retryTimer = null
        let delay = 1000
        let failedAttempts = 0
        setState('connecting')

        const connect = () => {
            const socket = new WebSocket(url)
            socketRef.current = socket
            let opened = false

            socket.onopen = () => {
                opened = true
                failedAttempts = 0
                delay = 1000
                setState('connected')
            }
            socket.onmessage = (event) => handlersRef.current.onMessage?.(event)
            socket.onclose = () => {
                if (disposed) return
                socketRef.current = null
                setState('disconnected')
                if (!opened && ++failedAttempts >= MAX_FAILED_ATTEMPTS) {
                    handlersRef.current.onSessionLost?.()
                    return
                }
                retryTimer = setTimeout(connect, delay)
                delay = Math.min(delay * 2, 30000)
            }
        }

        connect()
        return () => {
            disposed = true
            clearTimeout(retryTimer)
            socketRef.current?.close()
            socketRef.current = null
        }
    }, [url])

    return { state, socketRef }
}

export const Camera = () => {

    const videoRef = useRef(null)
    const canvasRef = useRef(null)
    const streamRef = useRef(null)
    const encodingRef = useRef(false)
    const [stream, setStream] = useState(null)
    const [error, setError] = useState(null)
    const [session, setSession] = useState(null)
    const [sessionFailed, setSessionFailed] = useState(false)
    const [sessionNonce, setSessionNonce] = useState(0)
    const [peers, setPeers] = useState(NO_PEERS)
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
            setSessionFailed(false)
            const restored = restoreSession()
            if (restored) {
                setSession(restored)
                return
            }
            try {
                const createdSession = await requestSession(controller.signal)
                sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(createdSession))
                setSession(createdSession)
            } catch (err) {
                if (err.name !== 'AbortError') {
                    setSessionFailed(true)
                    setError(err.message || 'Failed to create session')
                }
            }
        }

        createSession()
        return () => controller.abort()
    }, [sessionNonce])

    const handleSessionLost = useCallback(() => {
        sessionStorage.removeItem(SESSION_STORAGE_KEY)
        setSession(null)
        setPeers(NO_PEERS)
        setSource('')
        setSessionNonce(nonce => nonce + 1)
    }, [])

    const paths = session?.websocketPaths
    const videoUrl = useMemo(
        () => (session ? websocketUrl(paths?.video || DEFAULT_PATHS.video, session.browserToken) : null),
        [session, paths],
    )
    const anglesUrl = useMemo(
        () => (session ? websocketUrl(paths?.angles || DEFAULT_PATHS.angles, session.browserToken) : null),
        [session, paths],
    )

    const handleAnglesMessage = useCallback((event) => {
        if (typeof event.data !== 'string') return
        try {
            const message = JSON.parse(event.data)
            if (message.type === 'status') {
                setPeers({ python: Boolean(message.python), unity: Boolean(message.unity) })
                setSource(message.source || '')
            }
        } catch {
            setError('Failed to parse message from server')
        }
    }, [])

    const { state: videoState, socketRef: videoSocketRef } = useChannel(videoUrl, undefined, handleSessionLost)
    const { state: anglesState } = useChannel(anglesUrl, handleAnglesMessage, handleSessionLost)

    const channelsConnected = videoState === 'connected' && anglesState === 'connected'
    const connectionStatus = channelsConnected
        ? 'connected'
        : sessionFailed || videoState === 'disconnected' || anglesState === 'disconnected'
            ? 'disconnected'
            : 'connecting'

    useEffect(() => {
        if (anglesState !== 'connected') {
            setPeers(NO_PEERS)
            setSource('')
        }
    }, [anglesState])

    useEffect(() => {
        if (source !== 'remote_camera' || !channelsConnected) {
            stopCamera()
        }
    }, [source, channelsConnected, stopCamera])

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
        if (!stream) return undefined

        const interval = setInterval(() => {
            const socket = videoSocketRef.current
            const video = videoRef.current
            const canvas = canvasRef.current
            if (encodingRef.current || !video || !canvas || socket?.readyState !== WebSocket.OPEN) return
            if (!video.videoWidth || !video.videoHeight) return
            // Sieć nie nadąża: pomijamy klatkę zamiast kolejkować opóźnienie.
            if (socket.bufferedAmount > MAX_BUFFERED_BYTES) return

            encodingRef.current = true
            canvas.width = 640
            canvas.height = 480
            canvas.getContext('2d').drawImage(video, 0, 0, 640, 480)
            canvas.toBlob((blob) => {
                try {
                    if (blob && blob.size <= MAX_FRAME_BYTES && socket.readyState === WebSocket.OPEN) socket.send(blob)
                } finally {
                    encodingRef.current = false
                }
            }, 'image/jpeg', 0.7)
        }, FRAME_INTERVAL_MS)

        return () => {
            clearInterval(interval)
            encodingRef.current = false
        }
    }, [stream, videoSocketRef])

    const webCameraReady = peers.python && source === 'remote_camera' && channelsConnected
    const expiresAt = session
        ? new Date(session.expiresAt).toLocaleString('pl-PL', { hour: '2-digit', minute: '2-digit' })
        : '-'

    return (
        <>
            <main className="camera-page">
                <header className="camera-header">
                    <div>
                        <span className="eyebrow">Transmisja obrazu</span>
                        <h1>Kamera sterująca</h1>
                        <p>Przekaż obraz do lokalnego systemu analizy gestów.</p>
                    </div>
                    <div className={`connection-status connection-status--${connectionStatus}`} role="status">
                        <span className="connection-status__dot" aria-hidden="true" />
                        {connectionStatus === 'connected'
                            ? 'Serwer połączony'
                            : connectionStatus === 'connecting'
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