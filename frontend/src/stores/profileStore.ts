import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

interface ProfileStore {
  avatarDataUrl: string | null
  setAvatarDataUrl: (avatarDataUrl: string | null) => void
}

export const useProfileStore = create<ProfileStore>()(
  persist(
    (set) => ({
      avatarDataUrl: null,
      setAvatarDataUrl: (avatarDataUrl) => set({ avatarDataUrl }),
    }),
    {
      name: 'clinical-qa-profile',
      storage: createJSONStorage(() => localStorage),
    }
  )
)
