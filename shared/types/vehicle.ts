/** Vehicle-related types. */

export interface Vehicle {
  id: string;
  ownerId: string;
  plateNumber: string;
  make: string;
  model: string;
  year: number;
  createdAt: string;
}

export interface Owner {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  createdAt: string;
}
