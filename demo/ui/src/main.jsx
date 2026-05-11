import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import NereidDemo from './NereidDemo'


createRoot(document.getElementById('root')).render(
  <StrictMode>
    <NereidDemo />
  </StrictMode>,
)
