import { Link } from 'react-router-dom'
import "../styles/home.css"

const RELEASES_URL = 'https://github.com/timon0420/Projekt-inzynierski/releases/latest'
const DESKTOP_APP_URL = import.meta.env.VITE_DESKTOP_APP_URL || RELEASES_URL
const VISUALIZATION_URL = import.meta.env.VITE_VISUALIZATION_URL || RELEASES_URL

const icons = {
    camera: (
        <>
            <rect x="3" y="6" width="13" height="12" rx="2.5" />
            <path d="m16 10.5 5-3v9l-5-3" />
        </>
    ),
    app: (
        <>
            <rect x="3" y="4" width="18" height="13" rx="2" />
            <path d="M8 21h8M12 17v4M9 10.5l2 2 4-4" />
        </>
    ),
    arm: (
        <>
            <path d="M5 20h10M7 20v-3h6v3" />
            <circle cx="10" cy="14" r="1.6" />
            <path d="m10.8 12.6 3.4-5.2" />
            <circle cx="15" cy="6" r="1.6" />
            <path d="m16.5 6.5 3 2.5M19.5 9l1 2.5" />
        </>
    ),
    text: (
        <>
            <path d="M6 3h9l4 4v14H6z" />
            <path d="M14 3v5h5M9 12h7M9 16h5" />
        </>
    ),
}

const Icon = ({ name }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {icons[name]}
    </svg>
)

const TileContent = ({ icon, title, text, action }) => (
    <>
        <span className="home-tile__icon"><Icon name={icon} /></span>
        <span className="home-tile__body">
            <strong>{title}</strong>
            <span>{text}</span>
        </span>
        <span className="home-tile__action">{action}<span aria-hidden="true">→</span></span>
    </>
)

const modules = [
    {
        name: 'Aplikacja desktopowa',
        text: 'Odpowiada za akwizycję i analizę obrazu. Na podstawie położenia dłoni oblicza kąty niezbędne do sterowania modelem manipulatora. Stanowi domyślny sposób pozyskiwania obrazu — z kamery podłączonej do komputera.',
    },
    {
        name: 'Aplikacja webowa',
        text: 'Umożliwia przesyłanie obrazu z urządzeń mobilnych, takich jak smartfony, co ułatwia przygotowanie stanowiska. Zawiera również informacje potrzebne do poprawnego korzystania z systemu.',
    },
    {
        name: 'Serwer WebSocket',
        text: 'Pośredniczy w wymianie danych pomiędzy modułami. Przekazuje wartości kątów z aplikacji desktopowej do modelu manipulatora oraz klatki wideo z aplikacji webowej do aplikacji desktopowej.',
    },
    {
        name: 'Model manipulatora',
        text: 'Wizualizacja przygotowana w środowisku Unity, która w czasie rzeczywistym prezentuje rezultaty działania systemu.',
    },
]

const steps = [
    'Pobierz i uruchom aplikację sterującą oraz wizualizację manipulatora.',
    'W aplikacji sterującej wybierz źródło obrazu: kamerę lokalną lub kamerę webową.',
    'Przy kamerze webowej otwórz transmisję wideo na telefonie i wpisz wyświetlony kod sesji w aplikacji sterującej.',
    'Umieść dłoń w kadrze — model manipulatora będzie podążał za jej ruchem.',
]

export const Home = () => {
    return (
        <main className="home-page">
            <header className="home-hero">
                <span className="eyebrow">Projekt inżynierski</span>
                <h1>System sterowania modelem manipulatora robota z wykorzystaniem systemu wizyjnego</h1>
                <p>Steruj wirtualnym ramieniem robota ruchem dłoni, rejestrowanym przez kamerę komputera lub smartfona.</p>
            </header>

            <nav className="home-tiles" aria-label="Moduły systemu">
                <Link className="home-tile home-tile--primary" to="/camera">
                    <TileContent icon="camera" title="Transmisja wideo" text="Użyj smartfona jako kamery systemu." action="Otwórz" />
                </Link>
                <a className="home-tile" href={DESKTOP_APP_URL} target="_blank" rel="noopener noreferrer">
                    <TileContent icon="app" title="Aplikacja sterująca" text="Analiza obrazu i wyznaczanie kątów." action="Pobierz" />
                </a>
                <a className="home-tile" href={VISUALIZATION_URL} target="_blank" rel="noopener noreferrer">
                    <TileContent icon="arm" title="Wizualizacja systemu sterowania" text="Model manipulatora w środowisku Unity." action="Pobierz" />
                </a>
                <a className="home-tile" href="#opis-projektu">
                    <TileContent icon="text" title="Opis projektu" text="Cel, budowa i sposób użycia systemu." action="Czytaj" />
                </a>
            </nav>

            <section id="opis-projektu" className="home-about" aria-labelledby="opis-projektu-title">
                <div className="home-about__intro">
                    <span className="eyebrow">Opis projektu</span>
                    <h2 id="opis-projektu-title">O projekcie</h2>
                    <p>
                        Projekt powstał w ramach pracy inżynierskiej na kierunku Informatyka. Jego celem jest
                        umożliwienie użytkownikowi sterowania wirtualnym modelem manipulatora robota za pomocą
                        systemu wizyjnego. System pokazuje możliwości nowoczesnych metod analizy obrazu oraz
                        zastosowania, jakie przed nimi stoją.
                    </p>
                    <p>Ze względu na swoją charakterystykę projekt został podzielony na kilka współpracujących modułów.</p>
                </div>

                <ol className="home-modules">
                    {modules.map(({ name, text }, index) => (
                        <li key={name} className="home-module">
                            <span className="home-module__index">{String(index + 1).padStart(2, '0')}</span>
                            <h3>{name}</h3>
                            <p>{text}</p>
                        </li>
                    ))}
                </ol>

                <div className="home-steps">
                    <h3>Jak zacząć</h3>
                    <ol>
                        {steps.map(step => <li key={step}>{step}</li>)}
                    </ol>
                </div>
            </section>

            <footer className="home-footer">
                <span>Projekt inżynierski · Informatyka</span>
                <a href="#top" onClick={(event) => { event.preventDefault(); window.scrollTo({ top: 0 }) }}>Do góry ↑</a>
            </footer>
        </main>
    )
}
