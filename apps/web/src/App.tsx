import { NavLink, Route, Routes } from 'react-router-dom'
import HomePage from './pages/HomePage'
import UploadPage from './pages/UploadPage'
import ItemsPage from './pages/ItemsPage'
import ItemDetailPage from './pages/ItemDetailPage'
import SpacesPage from './pages/SpacesPage'
import GraphPage from './pages/GraphPage'
import HistoryPage from './pages/HistoryPage'
import TeamsPage from './pages/TeamsPage'
import TeamDetailPage from './pages/TeamDetailPage'
import TokensPage from './pages/TokensPage'
import LoginPage from './pages/LoginPage'
import ThemeToggle from './components/ThemeToggle'
import RequireAuth from './auth/RequireAuth'
import { useAuth } from './auth/AuthContext'

function UserMenu() {
  const { mode, user, logout } = useAuth()
  if (mode === 'dev' || !user) return null
  return (
    <span className="nav-user" style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
      <span className="meta" title={user.email ?? user.id}>
        {user.name ?? user.id}
      </span>
      <button type="button" className="nav-link" onClick={logout}>
        Sign out
      </button>
    </span>
  )
}

function NavBar() {
  return (
    <nav className="nav-bar">
      <span className="nav-brand"><span className="dot" />k7e</span>
      <NavLink to="/" end className="nav-link">Home</NavLink>
      <NavLink to="/items" className="nav-link">Items</NavLink>
      <NavLink to="/spaces" className="nav-link">Spaces</NavLink>
      <NavLink to="/graph" className="nav-link">Graph</NavLink>
      <NavLink to="/history" className="nav-link">History</NavLink>
      <NavLink to="/teams" className="nav-link">Teams</NavLink>
      <NavLink to="/tokens" className="nav-link">Tokens</NavLink>
      <NavLink to="/upload" className="btn btn-primary">Upload</NavLink>
      <UserMenu />
      <ThemeToggle />
    </nav>
  )
}

function ProtectedApp() {
  return (
    <RequireAuth>
      <NavBar />
      <div className="content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/items" element={<ItemsPage />} />
          <Route path="/items/:slug" element={<ItemDetailPage />} />
          <Route path="/spaces" element={<SpacesPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/teams" element={<TeamsPage />} />
          <Route path="/teams/:slug" element={<TeamDetailPage />} />
          <Route path="/tokens" element={<TokensPage />} />
        </Routes>
      </div>
    </RequireAuth>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/*" element={<ProtectedApp />} />
    </Routes>
  )
}
