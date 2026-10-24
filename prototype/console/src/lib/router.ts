import { useEffect, useState } from 'react'

export type Route =
  | { name: 'scenarios' }
  | { name: 'cases' }
  | { name: 'new' }
  | { name: 'case'; id: string }
  | { name: 'memory' }
  | { name: 'rulebook' }
  | { name: 'evaluation' }

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  switch (parts[0]) {
    case 'cases':
      return { name: 'cases' }
    case 'new':
      return { name: 'new' }
    case 'case':
      return parts[1] ? { name: 'case', id: parts[1] } : { name: 'cases' }
    case 'memory':
      return { name: 'memory' }
    case 'rulebook':
      return { name: 'rulebook' }
    case 'evaluation':
      return { name: 'evaluation' }
    default:
      return { name: 'scenarios' }
  }
}

export function href(route: Route): string {
  switch (route.name) {
    case 'case':
      return `#/case/${route.id}`
    default:
      return `#/${route.name}`
  }
}

export function go(route: Route) {
  window.location.hash = href(route)
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash))
  useEffect(() => {
    const onHash = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return route
}
