import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/hind/400.css'
import '@fontsource/hind/500.css'
import '@fontsource/hind/600.css'
import '@fontsource/hind/700.css'
import '@fontsource/khand/500.css'
import '@fontsource/khand/600.css'
import '@fontsource-variable/noto-sans-devanagari'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
