import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import { useAuthStore } from './auth'
import { searchApi } from '@/services/searchApi'
import type { SearchCapabilities } from '@/types/search'

export const useGlobalSearchStore = defineStore('globalSearch', () => {
  const auth = useAuthStore()
  const isOpen = ref(false)
  const capabilities = shallowRef<SearchCapabilities>({
    enabled: false,
    ready: false,
    hybrid_available: false,
  })

  const enabled = computed(() => auth.isAuthenticated && capabilities.value.enabled)

  let controller: AbortController | undefined
  let generation = 0

  const loadCapabilities = async () => {
    const token = ++generation
    controller?.abort()
    controller = new AbortController()
    isOpen.value = false
    capabilities.value = { enabled: false, ready: false, hybrid_available: false }
    if (!auth.isAuthenticated) return
    try {
      const result = await searchApi.capabilities(controller.signal)
      if (token === generation) {
        capabilities.value = result
      }
    } catch {
      /* Search failure does not affect the application shell. */
    }
  }

  const openSearch = () => {
    if (enabled.value) {
      isOpen.value = true
    }
  }

  const closeSearch = () => {
    isOpen.value = false
  }

  const toggleSearch = () => {
    if (isOpen.value) {
      closeSearch()
    } else {
      openSearch()
    }
  }

  const setOpen = (val: boolean) => {
    isOpen.value = val
  }

  return {
    isOpen,
    capabilities,
    enabled,
    loadCapabilities,
    openSearch,
    closeSearch,
    toggleSearch,
    setOpen,
  }
})
