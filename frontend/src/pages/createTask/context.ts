import { createContext, useContext } from 'react'
import type { CreateTaskModel } from './useCreateTaskModel'

export const CreateTaskContext = createContext<CreateTaskModel | null>(null)

/** The New build page's state, for the step components rendered inside it. */
export function useCreateTask(): CreateTaskModel {
  const model = useContext(CreateTaskContext)
  if (!model) throw new Error('useCreateTask must be used inside CreateTaskContext.Provider')
  return model
}
