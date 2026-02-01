import { Wrench } from "lucide-react";
import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="py-12 bg-white border-t-2 border-orange-100">
      <div className="container px-4">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-600 to-orange-500 flex items-center justify-center shadow-md group-hover:shadow-lg transition-shadow">
              <Wrench className="w-4 h-4 text-white" />
            </div>
            <span className="font-black text-gray-900 tracking-tight text-lg">
              Handy<span className="text-orange-600">Daddy</span>
            </span>
          </Link>

          {/* Copyright */}
          <p className="text-sm text-gray-700 font-bold uppercase tracking-wide">
            © {new Date().getFullYear()} HandyDaddy — Your AI-powered home repair assistant
          </p>
        </div>
      </div>
    </footer>
  );
}
